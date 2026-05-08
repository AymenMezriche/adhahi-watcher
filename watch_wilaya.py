#!/usr/bin/env python3
"""
Adhahi Wilaya watcher for Railway.
Monitors wilaya availability and sends Telegram alerts.
"""
from __future__ import annotations
import datetime as dt
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
import requests

# Unbuffer stdout for Railway logs
sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)

API_URL = "https://adhahi.dz/api/v1/public/wilaya-quotas"
TARGET_WILAYA_CODES = ["21", "23", "24"]
CHECK_INTERVAL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 12

ADHAHI_COOKIE = os.getenv("ADHAHI_COOKIE", "").strip()
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8556389722:AAEc1mUOy1oSlTM1O5lDjQGceUqqKpbIraA").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5325084571").strip()

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Origin": "https://adhahi.dz",
    "Referer": "https://adhahi.dz/register",
}

@dataclass
class WilayaQuota:
    wilaya_code: str
    name_ar: str
    name_fr: str
    available: bool

def ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def parse_wilaya(raw: Any) -> WilayaQuota | None:
    if not isinstance(raw, dict):
        return None
    code = raw.get("wilayaCode")
    name_ar = raw.get("wilayaNameAr")
    name_fr = raw.get("wilayaNameFr")
    available = raw.get("available")
    
    if not isinstance(code, str):
        return None
    if not isinstance(name_ar, str):
        name_ar = ""
    if not isinstance(name_fr, str):
        name_fr = ""
    if not isinstance(available, bool):
        return None
    
    return WilayaQuota(
        wilaya_code=code,
        name_ar=name_ar,
        name_fr=name_fr,
        available=available,
    )

def fetch_wilayas() -> list[WilayaQuota]:
    headers = dict(DEFAULT_HEADERS)
    if ADHAHI_COOKIE:
        headers["Cookie"] = ADHAHI_COOKIE
    
    response = requests.get(API_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    
    if response.status_code != 200:
        content_type = response.headers.get("content-type", "")
        preview = response.text[:220].replace("\n", " ")
        raise RuntimeError(
            f"HTTP {response.status_code}; content-type='{content_type}'; "
            f"body-preview={preview!r}"
        )
    
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        preview = response.text[:200].replace("\n", " ")
        raise RuntimeError(
            f"Unexpected content-type '{content_type}'. Body preview: {preview!r}"
        )
    
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected JSON shape: expected a list")
    
    wilayas: list[WilayaQuota] = []
    for item in payload:
        parsed = parse_wilaya(item)
        if parsed is not None:
            wilayas.append(parsed)
    
    if not wilayas:
        raise RuntimeError("Parsed zero valid wilaya records")
    
    return wilayas

def find_target(wilayas: list[WilayaQuota], code: str) -> WilayaQuota | None:
    for wilaya in wilayas:
        if wilaya.wilaya_code == code:
            return wilaya
    return None

def send_telegram_message(message: str) -> None:
    if not TELEGRAM_ENABLED:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[{ts()}] WARN: Telegram enabled but token/chat_id missing.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            preview = resp.text[:200].replace("\n", " ")
            print(
                f"[{ts()}] WARN: Telegram send failed HTTP {resp.status_code}; "
                f"body-preview={preview!r}"
            )
    except requests.RequestException as exc:
        print(f"[{ts()}] WARN: Telegram request failed: {exc}")

def main() -> None:
    previous_available: dict[str, bool] = {}
    
    print(
        f"[{ts()}] Starting watcher. Target wilayaCodes={','.join(TARGET_WILAYA_CODES)}, "
        f"interval={CHECK_INTERVAL_SECONDS}s"
    )
    
    send_telegram_message(
        f"Adhahi watcher started. Monitoring wilayas {', '.join(TARGET_WILAYA_CODES)} "
        f"every {CHECK_INTERVAL_SECONDS}s."
    )
    
    while True:
        try:
            wilayas = fetch_wilayas()
            for code in TARGET_WILAYA_CODES:
                target = find_target(wilayas, code)
                if target is None:
                    print(
                        f"[{ts()}] WARN: Target wilayaCode={code} not found "
                        f"in API response (records={len(wilayas)})."
                    )
                    continue
                
                if code not in previous_available:
                    previous_available[code] = target.available
                    print(
                        f"[{ts()}] Baseline set -> {target.wilaya_code} "
                        f"({target.name_fr} / {target.name_ar}) available={target.available}"
                    )
                else:
                    if (not previous_available[code]) and target.available:
                        print(
                            f"[{ts()}] AVAILABLE: {target.wilaya_code} "
                            f"({target.name_fr} / {target.name_ar}) changed false -> true"
                        )
                        send_telegram_message(
                            f"Adhahi AVAILABLE: Wilaya {target.wilaya_code} "
                            f"({target.name_fr} / {target.name_ar}) changed false -> true."
                        )
                    else:
                        print(
                            f"[{ts()}] Heartbeat: {target.wilaya_code} "
                            f"available={target.available}"
                        )
                    previous_available[code] = target.available
        
        except requests.RequestException as exc:
            print(f"[{ts()}] ERROR: Network/request issue: {exc}")
        except ValueError as exc:
            print(f"[{ts()}] ERROR: Failed to parse JSON: {exc}")
        except Exception as exc:
            print(f"[{ts()}] ERROR: {exc}")
        
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
