"""Submit kube job"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import typer
import yaml
from hydra import compose, initialize_config_dir

from kubernetes.manifest import MANIFEST_BY_FNAME

# pass filename to basicConfig to write logs to file
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

KUBE_SECRET_SPECS = [
    ("git-cluster-token", "cluster-token", "GIT_CLUSTER_PAT", True),
    ("wandb-api-key", "api-key", "WANDB_API_KEY", False),
]


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Render and submit a Kubernetes PyTorchJob manifest.")
    # TODO: change the default depending on the cluster
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=Path(__file__).with_name("template.yaml"),
        help="Path to the kube manifest YAML file.",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        required=True,
        help="Path to the Hydra config YAML file (e.g., config.yaml)",
    )
    parser.add_argument(
        "--cluster",
        type=str,
        default="volt",
        help="volt or llabs",
    )
    return parser.parse_known_args(argv)


def _apply_secret(secret_name: str, secret_key: str, env_var_name: str, env_var_value: str, namespace: str | None) -> None:
    create_cmd = [
        "kubectl",
        "create",
        "secret",
        "generic",
        secret_name,
        f"--from-literal={secret_key}={env_var_value}",
        "--dry-run=client",
        "-o",
        "yaml",
    ]
    apply_cmd = ["kubectl", "apply", "-f", "-"]
    if namespace:
        create_cmd.extend(["--namespace", namespace])
        apply_cmd.extend(["--namespace", namespace])

    create = subprocess.Popen(
        create_cmd,
        stdout=subprocess.PIPE,
    )

    subprocess.run(
        apply_cmd,
        stdin=create.stdout,
        check=True,
    )
    print(f"Synchronized secret {secret_name} from {env_var_name}")


def _sync_kube_secrets_from_env(namespace: str | None) -> None:
    for secret_name, secret_key, env_var_name, required in KUBE_SECRET_SPECS:
        env_var_value = os.environ.get(env_var_name)
        if not env_var_value:
            if required:
                raise ValueError(f"Please set {env_var_name} as an environment variable.")
            continue
        _apply_secret(secret_name, secret_key, env_var_name, env_var_value, namespace)


def _print_kube_context():
    """Print the current kubectl context and available contexts."""
    log.info("\nCurrent kubectl context:")
    subprocess.run(["kubectl", "config", "current-context"])
    log.info("\nAvailable contexts:")
    subprocess.run(["kubectl", "config", "get-contexts"])


def load_config(args, overrides):
    config_path = args.config_path.resolve()
    config_dir = config_path.parent
    config_name = config_path.stem
    with initialize_config_dir(version_base=None, config_dir=str(config_dir)):
        cfg = compose(config_name=config_name, overrides=overrides)
    return cfg


def resolve_manifest(manifest_path: str | Path, cfg):
    fname = Path(manifest_path).name

    try:
        manifest_cls = MANIFEST_BY_FNAME[fname]
    except KeyError as exc:
        known = ", ".join(sorted(MANIFEST_BY_FNAME))
        raise ValueError(f"Unknown manifest template '{fname}'. Known templates: {known}") from exc

    return manifest_cls.from_config(cfg)


def extract_manifest_namespace(manifest_text: str) -> str | None:
    manifest = yaml.safe_load(manifest_text)
    if not isinstance(manifest, dict):
        return None
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        return None
    namespace = metadata.get("namespace")
    return namespace if isinstance(namespace, str) and namespace else None


def submit_manifest(manifest_text: str, kube_job_name: str, namespace: str | None = None):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as temp_job:
        temp_job.write(manifest_text)
        temp_job_path = temp_job.name

    try:
        _sync_kube_secrets_from_env(namespace)
        print(f"Submitting PyTorch Job: {kube_job_name}")
        # NOTE: create throws exception if the job already exists
        # if using create, then job name needs to be unique
        result = subprocess.run(
            ["kubectl", "create", "-f", temp_job_path],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_job_path)
        except OSError:
            pass


def post_submit(retcode: int, stderr: str, kube_job_name: str) -> None:
    """
    Print post-submission information.

    Args:
        cfg: Config object
        retcode: kubectl return code
        stderr: kubectl stderr
    """
    # TODO
    # Print W&B information (using utility function for consistent styling)
    # utils.print_wandb_info(cfg)

    if retcode == 0:
        # Success
        # output_path = f"{cfg.project.dir.output}/{cfg.project.wandb.run_name}"

        print(f"{typer.style('Successfully submitted PyTorch Job:', fg=typer.colors.GREEN)} {kube_job_name}")
        # print(f"Output files will be in: {typer.style(output_path, fg=typer.colors.CYAN)}")
        print()
        print("Useful commands:")
        print(f"  List jobs:     {typer.style('kubectl get pytorchjobs | grep ', fg=typer.colors.YELLOW)}")
        print(f"  Delete job:    {typer.style(f'kubectl delete pytorchjob {kube_job_name}', fg=typer.colors.YELLOW)}")
        print(f"  Watch job:     {typer.style(f'src/kubernetes/watch.py {kube_job_name}', fg=typer.colors.YELLOW)}")
        print(f"  List pods:     {typer.style('kubectl get pods | grep ', fg=typer.colors.YELLOW)}")
        print(f"  View logs:     {typer.style(f'kubectl logs -f {kube_job_name}', fg=typer.colors.YELLOW)}")
    else:
        # Failure
        print(
            f"Failed to submit PyTorch Job. Exit code: {retcode}",
            file=sys.stderr,
        )
        print(stderr, file=sys.stderr)
        raise RuntimeError(f"kubectl submission failed with exit code {retcode}")


def main():
    args, overrides = parse_args()
    _print_kube_context()
    log.info(f"Submitting to {args.cluster} cluster using manifest {args.manifest_path}")
    cfg = load_config(args, overrides)
    # instantiate class from cfg
    manifest = resolve_manifest(args.manifest_path, cfg)
    # include the rest of derived vars
    manifest_text = manifest.render(args.manifest_path)
    namespace = extract_manifest_namespace(manifest_text)
    retcode, _, stderr = submit_manifest(manifest_text, manifest.kube_job_name, namespace)
    post_submit(retcode, stderr, manifest.kube_job_name)


if __name__ == "__main__":
    raise SystemExit(main())
