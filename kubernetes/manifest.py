"""Build and render Kubernetes manifests."""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import ClassVar

from kubernetes import utils


@dataclass(frozen=True, slots=True)
class BaseManifest:
    fname: ClassVar[str]

    @staticmethod
    def _build_kube_job_name(cfg) -> str:
        return utils.add_timestamp(cfg.experiment.wandb.run_name)

    @staticmethod
    def _build_memory_per_node(cfg) -> int:
        return cfg.resource.memory_per_cpu * cfg.resource.cpus_per_node

    @staticmethod
    def _build_git_repo_host_path(cfg) -> str:
        return cfg.experiment.git.repo_url.removeprefix("https://")

    @staticmethod
    def _build_git_fetch_target(cfg) -> str:
        git_cfg = cfg.experiment.git
        commit_id = getattr(git_cfg, "commit_id", None)
        branch = getattr(git_cfg, "branch", None)

        if commit_id and branch:
            raise ValueError("Set only one of experiment.git.commit_id or experiment.git.branch")
        if commit_id:
            return commit_id
        if branch:
            return branch
        raise ValueError("Set either experiment.git.commit_id or experiment.git.branch")

    @staticmethod
    def _build_git_checkout_args(cfg) -> str:
        git_cfg = cfg.experiment.git
        commit_id = getattr(git_cfg, "commit_id", None)
        branch = getattr(git_cfg, "branch", None)

        if commit_id and branch:
            raise ValueError("Set only one of experiment.git.commit_id or experiment.git.branch")
        if commit_id:
            return "--detach FETCH_HEAD"
        if branch:
            return f'-B "{branch}" FETCH_HEAD'
        raise ValueError("Set either experiment.git.commit_id or experiment.git.branch")

    def _context(self) -> dict[str, object]:
        """Builds the env dict with both the class and derived vars"""
        context = {field.name.upper(): getattr(self, field.name) for field in fields(self)}
        return context

    @classmethod
    def from_config(cls, cfg, kube_job_name):
        """Instantiates the Manifest class from cfg"""
        raise NotImplementedError

    def render(self, manifest_path: str | Path):
        # assumes the manifest yamls are in the same dir level as this module
        resolved_manifest_path = Path(__file__).parent / manifest_path
        if not resolved_manifest_path.exists():
            raise FileNotFoundError(f"Manifest file not found: {resolved_manifest_path}")

        manifest_text = resolved_manifest_path.read_text()
        return manifest_text.format(**self._context())


@dataclass(frozen=True, slots=True)
class LambdaLabsManifest(BaseManifest):
    kube_job_name: str
    priority_label: str
    gc_user: str
    wandb_run_name: str
    git_repo_host_path: str
    git_fetch_target: str
    git_checkout_args: str
    docker_image: str
    num_nodes: int
    gpus_per_node: int
    entrypoint: str
    cpus_per_node: int
    memory_per_node: int
    worker_replica_spec: str
    fname: ClassVar[str] = "ll-template.yaml"

    @classmethod
    def from_config(cls, cfg) -> "LambdaLabsManifest":
        return cls(
            kube_job_name=cls._build_kube_job_name(cfg),
            priority_label=cfg.resource.priority_label,
            gc_user=cfg.experiment.gc_user,
            wandb_run_name=cfg.experiment.wandb.run_name,
            git_repo_host_path=cls._build_git_repo_host_path(cfg),
            git_fetch_target=cls._build_git_fetch_target(cfg),
            git_checkout_args=cls._build_git_checkout_args(cfg),
            docker_image=cfg.resource.docker_image,
            num_nodes=cfg.resource.num_nodes,
            gpus_per_node=cfg.resource.gpus_per_node,
            entrypoint=cfg.experiment.entrypoint,
            cpus_per_node=cfg.resource.cpus_per_node,
            memory_per_node=cls._build_memory_per_node(cfg),
            worker_replica_spec=cls._build_worker_replica_spec(cfg),
        )

    @staticmethod
    def _build_worker_replica_spec(cfg, spec_template: str = "latent_kv_template") -> str:
        worker_replicas = max(cfg.resource.num_nodes - 1, 0)
        if worker_replicas > 0:
            worker_spec = f"""
        Worker:
        replicas: {worker_replicas}
        restartPolicy: Never
        template: *{spec_template}
    """
        else:
            worker_spec = ""

        return worker_spec

# TODO: allow multiple fname template yaml for each manifest class
@dataclass(frozen=True, slots=True)
class VoltManifest(BaseManifest):
    kube_job_name: str
    gc_user: str
    git_repo_host_path: str
    git_fetch_target: str
    git_checkout_args: str
    gpus_per_node: int
    fname: ClassVar[str] = "template.yaml"

    @classmethod
    def from_config(cls, cfg) -> "VoltManifest":
        return cls(
            kube_job_name=cls._build_kube_job_name(cfg),
            gc_user=cfg.experiment.gc_user,
            git_repo_host_path=cls._build_git_repo_host_path(cfg),
            git_fetch_target=cls._build_git_fetch_target(cfg),
            git_checkout_args=cls._build_git_checkout_args(cfg),
            gpus_per_node=cfg.resource.gpus_per_node,
        )


MANIFEST_CLASSES = [
    LambdaLabsManifest,
    VoltManifest,
]

MANIFEST_BY_FNAME = {cls.fname: cls for cls in MANIFEST_CLASSES}
