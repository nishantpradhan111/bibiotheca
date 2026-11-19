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

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c "file:${agent_config}" \
  -s
