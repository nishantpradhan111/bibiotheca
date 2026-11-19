"""Validate rendered resources with bundled schemas; never connects to Kubernetes."""
import argparse
from pathlib import Path

import yaml
from kubernetes_validate import validate

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
parser.add_argument("--version", default="1.35.0")
args = parser.parse_args()
# PowerShell commonly writes a UTF-8 BOM; strip it so the first apiVersion parses normally.
resources = [item for item in yaml.safe_load_all(args.manifest.read_text(encoding="utf-8-sig")) if item]
if not resources:
    raise SystemExit("No Kubernetes resources found")
native_groups = {"v1", "apps", "batch", "autoscaling", "networking.k8s.io", "rbac.authorization.k8s.io"}
validated = 0
custom_resources = 0
for resource in resources:
    # CRD schemas are installed by their operators, not bundled in Kubernetes' built-in schema set.
    api_group = resource["apiVersion"].split("/", 1)[0]
    if api_group not in native_groups:
        custom_resources += 1
        print(f"Skipped custom resource {resource['kind']}/{resource['metadata']['name']}: validate with its installed CRD schema")
        continue
    validate(resource, args.version, strict=True)
    print(f"Validated {resource['kind']}/{resource['metadata']['name']}")
    validated += 1
print(f"Validated {validated} built-in resources against Kubernetes {args.version}; skipped {custom_resources} CRD resources; no cluster contacted.")
