"""评估报警规则（任务系统/命令行入口）。用法：python scripts/eval_alerts.py [--force]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alert_engine import evaluate_all


def main():
    ap = argparse.ArgumentParser(description="评估报警规则并推送")
    ap.add_argument("--force", action="store_true", help="忽略当日防重，强制评估")
    args = ap.parse_args()
    r = evaluate_all(force=args.force)
    if r.get("skipped"):
        print(f"[跳过] {r['reason']}")
        return
    print(f"[OK] 评估 {r['rules']} 条规则，触发 {r['triggered']} 条，"
          f"微信推送 {'成功' if r['notified'] else '未发送/失败'}")
    for e in r.get("errors", []):
        print(f"[错误] {e}")


if __name__ == "__main__":
    main()
