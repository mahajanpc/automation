#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

FEEDBACK_FILE = Path(__file__).resolve().parent / "feedback_history.json"

def load_feedback() -> list[str]:
    if FEEDBACK_FILE.exists():
        try:
            with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_feedback(feedback_list: list[str]):
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(feedback_list, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="Manage Feedback for Continuous Self-Improvement")
    parser.add_argument("--add", type=str, help="Add new feedback note to guide future Gemini generations")
    parser.add_argument("--list", action="store_true", help="List all recorded feedback")
    parser.add_argument("--clear", action="store_true", help="Clear all feedback")
    args = parser.parse_args()

    items = load_feedback()

    if args.add:
        items.append(args.add.strip())
        save_feedback(items)
        print(f"✅ Added feedback: '{args.add.strip()}'")
        print(f"Total feedback items recorded: {len(items)}")
    elif args.clear:
        save_feedback([])
        print("🗑️ Cleared all feedback history.")
    else:
        print("📋 Current Feedback History (injected into Gemini prompts):")
        if not items:
            print("  (No feedback recorded yet)")
        for idx, item in enumerate(items, 1):
            print(f"  {idx}. {item}")

if __name__ == "__main__":
    main()

