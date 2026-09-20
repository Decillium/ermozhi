import os
import yaml
import pytest

DEPLOY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "deploy", "azure")


class TestDeploymentManifestsValidation:

    def test_bicep_environment_template_exists_and_valid(self):
        bicep_path = os.path.join(DEPLOY_DIR, "environment.bicep")
        assert os.path.exists(bicep_path), f"Bicep template missing at {bicep_path}"

        with open(bicep_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Microsoft.OperationalInsights/workspaces" in content
        assert "Microsoft.App/managedEnvironments" in content
        assert "Microsoft.KeyVault/vaults" in content
        assert "Microsoft.Storage/storageAccounts" in content

    def test_gateway_manifest_guards_and_probes(self):
        gateway_yaml_path = os.path.join(DEPLOY_DIR, "gateway.yaml")
        assert os.path.exists(gateway_yaml_path), f"Gateway YAML missing at {gateway_yaml_path}"

        with open(gateway_yaml_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        assert manifest["name"] == "ermozhi-gateway"
        assert manifest["identity"]["type"] == "SystemAssigned"

        ingress = manifest["properties"]["configuration"]["ingress"]
        assert ingress["external"] is True
        assert ingress["targetPort"] == 8080

        # Verify scale-to-zero configuration for strict $0 cost budget
        scale = manifest["properties"]["template"]["scale"]
        assert scale["minReplicas"] == 0
        assert scale["maxReplicas"] == 2

        # Verify container resources and read-only root filesystem
        container = manifest["properties"]["template"]["containers"][0]
        assert container["resources"]["cpu"] == 0.25
        assert container["resources"]["memory"] == "0.5Gi"
        assert container["securityContext"]["readOnlyRootFilesystem"] is True

        # Verify liveness and readiness probes
        probes = container["probes"]
        assert len(probes) == 2
        probe_paths = [p["httpGet"]["path"] for p in probes]
        assert "/api/v1/health/live" in probe_paths
        assert "/api/v1/health/ready" in probe_paths

    def test_worker_manifest_guards_and_scaling(self):
        worker_yaml_path = os.path.join(DEPLOY_DIR, "worker.yaml")
        assert os.path.exists(worker_yaml_path), f"Worker YAML missing at {worker_yaml_path}"

        with open(worker_yaml_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        assert manifest["name"] == "ermozhi-worker"
        scale = manifest["properties"]["template"]["scale"]
        assert scale["minReplicas"] == 0
        assert scale["maxReplicas"] == 2

        container = manifest["properties"]["template"]["containers"][0]
        assert container["resources"]["cpu"] == 0.25
        assert container["resources"]["memory"] == "0.5Gi"
        assert container["securityContext"]["readOnlyRootFilesystem"] is True

    def test_container_apps_jobs_cron_schedules(self):
        jobs_dir = os.path.join(DEPLOY_DIR, "jobs")
        assert os.path.exists(jobs_dir), f"Jobs directory missing at {jobs_dir}"

        # 1. Market ingestion job
        ingestion_path = os.path.join(jobs_dir, "market-ingestion-job.yaml")
        assert os.path.exists(ingestion_path)
        with open(ingestion_path, "r", encoding="utf-8") as f:
            ingestion_job = yaml.safe_load(f)
        assert ingestion_job["properties"]["configuration"]["triggerType"] == "Schedule"
        assert "cronExpression" in ingestion_job["properties"]["configuration"]["scheduleTriggerConfig"]

        # 2. Reconciliation job
        reconciliation_path = os.path.join(jobs_dir, "reconciliation-job.yaml")
        assert os.path.exists(reconciliation_path)
        with open(reconciliation_path, "r", encoding="utf-8") as f:
            recon_job = yaml.safe_load(f)
        assert recon_job["properties"]["configuration"]["scheduleTriggerConfig"]["cronExpression"] == "*/15 * * * *"

        # 3. Media cleanup job
        cleanup_path = os.path.join(jobs_dir, "cleanup-job.yaml")
        assert os.path.exists(cleanup_path)
        with open(cleanup_path, "r", encoding="utf-8") as f:
            cleanup_job = yaml.safe_load(f)
        assert cleanup_job["properties"]["configuration"]["scheduleTriggerConfig"]["cronExpression"] == "0 2 * * *"
