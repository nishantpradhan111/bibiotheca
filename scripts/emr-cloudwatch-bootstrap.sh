#!/bin/bash
# Starts the CloudWatch agent with Flink, YARN container, and EMR step logs.
set -euo pipefail

agent_config=/tmp/digital-library-cloudwatch-agent.json
cat > "$agent_config" <<'JSON'
{
  "agent": {"run_as_user": "root"},
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/usr/lib/flink/log/*.log",
            "log_group_name": "/digital-library/analytics",
            "log_stream_name": "{instance_id}/flink",
            "publish_multi_logs": true,
            "timezone": "UTC"
          },
          {
            "file_path": "/mnt/var/log/hadoop-yarn/containers/*/*/stdout",
            "log_group_name": "/digital-library/analytics",
            "log_stream_name": "{instance_id}/yarn-stdout",
            "publish_multi_logs": true,
            "timezone": "UTC"
          },
          {
            "file_path": "/mnt/var/log/hadoop-yarn/containers/*/*/stderr",
            "log_group_name": "/digital-library/analytics",
            "log_stream_name": "{instance_id}/yarn-stderr",
            "publish_multi_logs": true,
            "timezone": "UTC"
          },
          {
            "file_path": "/mnt/var/log/hadoop/steps/*/stderr",
            "log_group_name": "/digital-library/analytics",
            "log_stream_name": "{instance_id}/emr-steps",
            "publish_multi_logs": true,
            "timezone": "UTC"
          },
          {
            "file_path": "/mnt/var/log/hadoop/steps/*/stdout",
            "log_group_name": "/digital-library/analytics",
            "log_stream_name": "{instance_id}/emr-steps-stdout",
            "publish_multi_logs": true,
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
JSON

# EMR bootstrap actions run before selected applications are installed. Apply
# the custom log configuration after the CloudWatch agent becomes available;
# otherwise a missing agent binary makes EMR terminate the cluster.
nohup bash -c '
  set -u
  agent_config="/tmp/digital-library-cloudwatch-agent.json"
  agent_ctl="/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl"
  for attempt in $(seq 1 60); do
    if [ -x "$agent_ctl" ]; then
      sudo "$agent_ctl" -m ec2 -a append-config -c "file:${agent_config}"
      sudo systemctl restart amazon-cloudwatch-agent
      exit 0
    fi
    sleep 10
  done
  echo "CloudWatch agent was not installed within the wait window; continuing without custom log forwarding."
  exit 0
' >/tmp/digital-library-cloudwatch-bootstrap.log 2>&1 &

exit 0
