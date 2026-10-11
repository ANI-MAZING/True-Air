"""Optional AWS sinks. Locally everything stays in memory; set the env vars on
App Runner (or anywhere with credentials) to persist events and send alerts.

  TRUEAIR_TABLE      DynamoDB table (pk: string "pk", sk: string "sk")
  TRUEAIR_TOPIC_ARN  SNS topic for school / regulator alerts
  TRUEAIR_NOTIFY_MIN_SECONDS  minimum gap between alert digests (default 600)
"""
import json
import logging
import os
import time
from decimal import Decimal

log = logging.getLogger("trueair.aws")
MAX_DIGEST_LINES = 15


class AwsSinks:
    def __init__(self):
        self.table_name = os.getenv("TRUEAIR_TABLE")
        self.topic_arn = os.getenv("TRUEAIR_TOPIC_ARN")
        self._table = self._sns = None
        self._pending = []
        self._last_sent = 0.0
        self.min_interval = float(os.getenv("TRUEAIR_NOTIFY_MIN_SECONDS", "600"))
        if self.table_name or self.topic_arn:
            import boto3
            if self.table_name:
                self._table = boto3.resource("dynamodb").Table(self.table_name)
            if self.topic_arn:
                self._sns = boto3.client("sns")

    @property
    def status(self):
        return {"dynamodb": self.table_name or None, "sns": self.topic_arn or None}

    def put_event(self, event):
        if not self._table:
            return
        try:
            item = json.loads(json.dumps(event), parse_float=Decimal)
            item["pk"] = f"{event['kind']}#{event.get('subject', '-')}"
            item["sk"] = event["t"]
            self._table.put_item(Item=item)
        except Exception as e:  # never let persistence break the simulation
            log.warning("DynamoDB put failed: %s", e)

    def notify(self, subject, message, kind):
        """Queue an alert. Alerts go out as one digest at most every
        TRUEAIR_NOTIFY_MIN_SECONDS (default 10 min), since the simulation
        runs a day every couple of minutes."""
        if not self._sns:
            return
        self._pending.append(f"[{kind}] {message}")
        del self._pending[:-200]
        self.flush()

    def flush(self, force=False):
        if not self._sns or not self._pending:
            return
        now = time.time()
        if not force and now - self._last_sent < self.min_interval:
            return
        lines = self._pending[-MAX_DIGEST_LINES:]
        dropped = len(self._pending) - len(lines)
        body = "\n\n".join(lines)
        if dropped:
            body = f"(+{dropped} earlier alerts not shown)\n\n" + body
        try:
            self._sns.publish(TopicArn=self.topic_arn,
                              Subject=f"TrueAir: {len(self._pending)} new alert(s)",
                              Message=body)
            self._pending.clear()
            self._last_sent = now
        except Exception as e:
            log.warning("SNS publish failed: %s", e)
