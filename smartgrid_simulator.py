"""
================================================================================
WATTWISE — SMART ELECTRICITY METER & HOUSEHOLD ENERGY SIMULATOR
All-in-One Standalone Streamlit Application File
================================================================================
Run with:
    streamlit run wattwise_standalone_app.py
Requirements:
    pip install streamlit plotly pandas numpy networkx
================================================================================
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
import networkx as nx
import sqlite3
import json
import os
import sys
import math
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple


# ==============================================================================
# SECTION 1: DATABASE PERSISTENCE LAYER (SQLite)
# ==============================================================================

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "wattwise_standalone.db")

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS junctions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        icon TEXT,
        max_capacity_watts REAL DEFAULT 4000.0,
        created_at TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS appliances (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        junction_id TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        rated_watts REAL NOT NULL,
        actual_watts REAL NOT NULL,
        is_on INTEGER DEFAULT 1,
        is_restricted INTEGER DEFAULT 0,
        is_essential INTEGER DEFAULT 0,
        daily_hours REAL DEFAULT 4.0,
        power_factor REAL DEFAULT 0.95,
        variable_load_type TEXT DEFAULT 'constant',
        variable_load_level TEXT DEFAULT 'normal',
        current_simulated_watts REAL DEFAULT 0.0,
        created_at TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_summaries (
        date TEXT PRIMARY KEY,
        total_kwh REAL NOT NULL,
        total_cost REAL NOT NULL,
        peak_watts REAL NOT NULL,
        appliance_breakdown_json TEXT,
        junction_breakdown_json TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS monthly_summaries (
        month_str TEXT PRIMARY KEY,
        total_kwh REAL NOT NULL,
        total_bill REAL NOT NULL,
        energy_charges REAL NOT NULL,
        fixed_charges REAL NOT NULL,
        taxes_surcharges REAL NOT NULL,
        subsidy REAL DEFAULT 0.0,
        state TEXT,
        discom TEXT,
        bill_data_json TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS energy_limits (
        id INTEGER PRIMARY KEY,
        monthly_kwh_limit REAL DEFAULT 400.0,
        daily_kwh_limit REAL DEFAULT 15.0,
        budget_inr REAL DEFAULT 3000.0,
        warning_thresholds_json TEXT DEFAULT '[0.70, 0.85, 1.0]',
        auto_restrict_enabled INTEGER DEFAULT 1,
        require_user_confirm INTEGER DEFAULT 1,
        updated_at TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        action_recommendation TEXT,
        is_resolved INTEGER DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS meter_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reading_date TEXT NOT NULL,
        main_meter_kwh REAL NOT NULL,
        submeter_sum_kwh REAL NOT NULL,
        difference_kwh REAL NOT NULL,
        difference_pct REAL NOT NULL,
        source TEXT DEFAULT 'simulated',
        notes TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS restriction_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        appliance_id TEXT NOT NULL,
        appliance_name TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT NOT NULL,
        current_monthly_kwh REAL,
        limit_kwh REAL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    conn.close()

def seed_default_data_if_empty():
    init_database()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM junctions")
    if cur.fetchone()[0] == 0:
        default_junctions = [
            ("junc_living", "Living Room Junction", "Living room entertainment, lighting, fan and sockets", "🛋️", 4000.0),
            ("junc_kitchen", "Kitchen Junction", "High-power cooking appliances, refrigerator, microwave", "🍳", 6000.0),
            ("junc_bed", "Bedroom Junction", "Air conditioning, bedroom ceiling fans, charging stations", "🛏️", 5000.0),
            ("junc_bath", "Bathroom Junction", "Water geysers, hair dryers, ventilation exhaust", "🚿", 4500.0),
            ("junc_cooling", "Cooling & Ventilation", "Central air cooler, additional split ACs, booster fans", "❄️", 5500.0),
            ("junc_utility", "Utility & Water Supply", "Washing machine, submersible water pump, iron", "⚡", 5000.0),
        ]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for jid, name, desc, icon, cap in default_junctions:
            cur.execute("INSERT INTO junctions (id, name, description, icon, max_capacity_watts, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (jid, name, desc, icon, cap, now))

    cur.execute("SELECT COUNT(*) FROM appliances")
    if cur.fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        default_appliances = [
            ("app_ac_bed", "1.5T Inverter Air Conditioner", "junc_bed", "Cooling", 1500.0, 1150.0, 1, 0, 0, 8.0, 0.95, "compressor_cycle", "normal", 1150.0),
            ("app_fridge_kit", "Double-Door Refrigerator (340L)", "junc_kitchen", "Kitchen", 180.0, 95.0, 1, 0, 1, 24.0, 0.88, "compressor_cycle", "normal", 95.0),
            ("app_geyser_bath", "Water Geyser / Storage Heater (25L)", "junc_bath", "Heavy Loads", 2000.0, 2000.0, 1, 0, 0, 1.5, 0.99, "constant", "normal", 2000.0),
            ("app_fan_living", "BLDC Ceiling Fan (Living)", "junc_living", "Ventilation", 32.0, 28.0, 1, 0, 0, 14.0, 0.92, "constant", "normal", 28.0),
            ("app_fan_bed", "BLDC Ceiling Fan (Bedroom)", "junc_bed", "Ventilation", 32.0, 28.0, 1, 0, 0, 10.0, 0.92, "constant", "normal", 28.0),
            ("app_tv_living", "55-inch 4K Smart TV & Soundbar", "junc_living", "Entertainment", 140.0, 120.0, 1, 0, 0, 5.0, 0.94, "constant", "normal", 120.0),
            ("app_microwave_kit", "Convection Microwave Oven", "junc_kitchen", "Kitchen", 1200.0, 1200.0, 0, 0, 0, 0.5, 0.96, "constant", "normal", 0.0),
            ("app_ind_kit", "Induction Cooktop (2000W)", "junc_kitchen", "Kitchen", 2000.0, 1600.0, 1, 0, 0, 1.5, 0.98, "two_stage", "normal", 1600.0),
            ("app_pump_util", "1 HP Submersible Water Pump", "junc_utility", "Heavy Loads", 750.0, 750.0, 1, 0, 0, 1.0, 0.85, "constant", "normal", 750.0),
            ("app_wm_util", "Front-Load Washing Machine", "junc_utility", "Heavy Loads", 1200.0, 450.0, 0, 0, 0, 1.0, 0.90, "two_stage", "normal", 0.0),
            ("app_laptop_bed", "Laptop & Workstation Setup", "junc_bed", "Electronics", 90.0, 65.0, 1, 0, 0, 8.0, 0.92, "constant", "normal", 65.0),
            ("app_led_living", "Living Room LED Lighting Array", "junc_living", "Lighting", 40.0, 40.0, 1, 0, 0, 6.0, 0.90, "constant", "normal", 40.0),
            ("app_led_bed", "Bedroom Ambient LED Lights", "junc_bed", "Lighting", 30.0, 30.0, 1, 0, 0, 5.0, 0.90, "constant", "normal", 30.0),
            ("app_router_living", "Dual-Band Wi-Fi 6 Router & ONT", "junc_living", "Electronics", 15.0, 12.0, 1, 0, 1, 24.0, 0.85, "constant", "normal", 12.0),
            ("app_iron_util", "Steam Clothes Iron", "junc_utility", "Heavy Loads", 1500.0, 1500.0, 0, 0, 0, 0.5, 0.99, "constant", "normal", 0.0)
        ]
        for item in default_appliances:
            cur.execute("""
            INSERT INTO appliances 
            (id, name, junction_id, category, rated_watts, actual_watts, is_on, is_restricted, is_essential, daily_hours, power_factor, variable_load_type, variable_load_level, current_simulated_watts, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*item, now))

    cur.execute("SELECT COUNT(*) FROM energy_limits")
    if cur.fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT INTO energy_limits (id, monthly_kwh_limit, daily_kwh_limit, budget_inr, warning_thresholds_json, auto_restrict_enabled, require_user_confirm, updated_at) VALUES (1, 420.0, 16.0, 3200.0, '[0.70, 0.85, 1.0]', 1, 1, ?)", (now,))

    settings_defaults = {
        "selected_state_tariff": "Maharashtra - MSEDCL",
        "sanctioned_load_kw": "4.0",
        "consumer_name": "Sanidhya Sharma",
        "consumer_no": "194028374102",
        "tolerance_pct": "3.0",
        "wire_loss_pct": "1.2"
    }
    for k, v in settings_defaults.items():
        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

def seed_realistic_historical_data():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM monthly_summaries")
    if cur.fetchone()[0] >= 6:
        conn.close()
        return

    cur.execute("DELETE FROM monthly_summaries")
    cur.execute("DELETE FROM daily_summaries")
    cur.execute("DELETE FROM meter_readings")

    random.seed(42)
    today = datetime.now().date()
    start_date = today - timedelta(days=180)

    cur.execute("SELECT id, name, junction_id, rated_watts, daily_hours FROM appliances")
    apps = [dict(r) for r in cur.fetchall()]

    current_date = start_date
    while current_date <= today:
        date_str = current_date.strftime("%Y-%m-%d")
        m = current_date.month
        ac_mult = 1.7 if m in [5, 6] else (1.0 if m in [7, 8] else 0.85)

        day_total_kwh = 0.0
        peak_w = 2800.0 + random.uniform(-200, 400)
        app_breakdown = {}
        junc_breakdown = {}

        for app in apps:
            mult = ac_mult if "ac" in app["id"] else random.uniform(0.85, 1.15)
            if current_date.weekday() >= 5:
                mult *= 1.15
            actual_hrs = max(0.2, app["daily_hours"] * mult * random.uniform(0.9, 1.1))
            eff_power = app["rated_watts"] * (0.85 if "ac" in app["id"] or "fridge" in app["id"] else 1.0)
            app_kwh = round((eff_power * actual_hrs) / 1000.0, 3)

            day_total_kwh += app_kwh
            app_breakdown[app["name"]] = app_kwh
            junc_breakdown[app["junction_id"]] = round(junc_breakdown.get(app["junction_id"], 0.0) + app_kwh, 3)

        day_total_kwh = round(day_total_kwh, 2)
        day_cost = round(day_total_kwh * 7.25, 2)

        cur.execute("""
        INSERT INTO daily_summaries (date, total_kwh, total_cost, peak_watts, appliance_breakdown_json, junction_breakdown_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (date_str, day_total_kwh, day_cost, round(peak_w, 1), json.dumps(app_breakdown), json.dumps(junc_breakdown)))

        if current_date.day in [1, 6, 11, 16, 21, 26]:
            submeter_kwh = day_total_kwh
            line_loss = submeter_kwh * 0.012
            noise = random.uniform(-0.02, 0.03) * submeter_kwh
            main_meter_kwh = round(submeter_kwh + line_loss + noise, 2)
            diff_kwh = round(main_meter_kwh - submeter_kwh, 2)
            diff_pct = round((diff_kwh / max(0.1, main_meter_kwh)) * 100.0, 2)

            cur.execute("""
            INSERT INTO meter_readings (reading_date, main_meter_kwh, submeter_sum_kwh, difference_kwh, difference_pct, source, notes)
            VALUES (?, ?, ?, ?, ?, 'simulated', 'Simulated smart meter synchronizer checkpoint')
            """, (date_str, main_meter_kwh, submeter_kwh, diff_kwh, diff_pct))

        current_date += timedelta(days=1)

    cur.execute("""
    SELECT strftime('%Y-%m', date) as m_str, SUM(total_kwh) as m_kwh 
    FROM daily_summaries GROUP BY m_str ORDER BY m_str
    """)
    month_rows = cur.fetchall()

    for row in month_rows:
        m_str = row["m_str"]
        m_kwh = round(row["m_kwh"], 1)
        units = m_kwh
        if units <= 100:
            energy_charges = units * 5.88
        elif units <= 300:
            energy_charges = 100 * 5.88 + (units - 100) * 11.26
        elif units <= 500:
            energy_charges = 100 * 5.88 + 200 * 11.26 + (units - 300) * 15.72
        else:
            energy_charges = 100 * 5.88 + 200 * 11.26 + 200 * 15.72 + (units - 500) * 17.81

        fixed_charges = 128.0
        wheeling = units * 1.38
        fuel_adj = units * 0.45
        tax_base = energy_charges + fixed_charges + wheeling + fuel_adj
        duty = tax_base * 0.16
        total_bill = round(tax_base + duty, 2)

        cur.execute("""
        INSERT OR REPLACE INTO monthly_summaries 
        (month_str, total_kwh, total_bill, energy_charges, fixed_charges, taxes_surcharges, subsidy, state, discom, bill_data_json)
        VALUES (?, ?, ?, ?, ?, ?, 0.0, 'Maharashtra', 'MSEDCL', '{}')
        """, (m_str, m_kwh, total_bill, round(energy_charges, 2), fixed_charges, round(wheeling + fuel_adj + duty, 2)))

    conn.commit()
    conn.close()

def get_all_junctions():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM junctions ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_all_appliances():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT a.*, j.name as junction_name, j.icon as junction_icon FROM appliances a JOIN junctions j ON a.junction_id = j.id ORDER BY a.name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def update_appliance_state(app_id: str, is_on: int, actual_watts: Optional[float] = None):
    conn = get_db_connection()
    cur = conn.cursor()
    if actual_watts is not None:
        cur.execute("UPDATE appliances SET is_on = ?, actual_watts = ?, current_simulated_watts = ? WHERE id = ?",
                    (is_on, actual_watts, actual_watts if is_on else 0.0, app_id))
    else:
        cur.execute("UPDATE appliances SET is_on = ?, current_simulated_watts = CASE WHEN ? = 1 THEN actual_watts ELSE 0.0 END WHERE id = ?",
                    (is_on, is_on, app_id))
    conn.commit()
    conn.close()

def update_appliance_full(app_id: str, data: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE appliances SET name = ?, junction_id = ?, category = ?, rated_watts = ?, actual_watts = ?, daily_hours = ?, power_factor = ?, is_essential = ?, is_on = ?, is_restricted = ? WHERE id = ?
    """, (data["name"], data["junction_id"], data.get("category", "General"), float(data["rated_watts"]), float(data["actual_watts"]), float(data["daily_hours"]), float(data.get("power_factor", 0.95)), int(data.get("is_essential", 0)), int(data.get("is_on", 1)), int(data.get("is_restricted", 0)), app_id))
    conn.commit()
    conn.close()

def add_appliance(app_dict: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    INSERT INTO appliances (id, name, junction_id, category, rated_watts, actual_watts, is_on, is_restricted, is_essential, daily_hours, power_factor, variable_load_type, variable_load_level, current_simulated_watts, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (app_dict["id"], app_dict["name"], app_dict["junction_id"], app_dict.get("category", "General"), float(app_dict["rated_watts"]), float(app_dict["actual_watts"]), int(app_dict.get("is_on", 1)), int(app_dict.get("is_restricted", 0)), int(app_dict.get("is_essential", 0)), float(app_dict.get("daily_hours", 4.0)), float(app_dict.get("power_factor", 0.95)), "constant", "normal", float(app_dict["actual_watts"]) if app_dict.get("is_on", 1) else 0.0, now))
    conn.commit()
    conn.close()

def delete_appliance(app_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM appliances WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()

def add_junction(junc_dict: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO junctions (id, name, description, icon, max_capacity_watts, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (junc_dict["id"], junc_dict["name"], junc_dict.get("description", ""), junc_dict.get("icon", "⚡"), float(junc_dict.get("max_capacity_watts", 4000.0)), now))
    conn.commit()
    conn.close()

def get_energy_limits():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM energy_limits WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"monthly_kwh_limit": 420.0, "daily_kwh_limit": 15.0, "budget_inr": 3200.0, "auto_restrict_enabled": 1}

def update_energy_limits(monthly_kwh: float, daily_kwh: float, budget_inr: float, auto_restrict: int):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE energy_limits SET monthly_kwh_limit = ?, daily_kwh_limit = ?, budget_inr = ?, auto_restrict_enabled = ?, updated_at = ? WHERE id = 1",
                (monthly_kwh, daily_kwh, budget_inr, auto_restrict, now))
    conn.commit()
    conn.close()

def get_app_settings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM app_settings")
    res = {row["key"]: row["value"] for row in cur.fetchall()}
    conn.close()
    return res

def update_app_setting(key: str, value: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_monthly_summaries():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM monthly_summaries ORDER BY month_str ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_daily_summaries(limit_days: int = 30):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM daily_summaries ORDER BY date DESC LIMIT ?", (limit_days,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return list(reversed(rows))

def get_meter_readings(limit: int = 50):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM meter_readings ORDER BY reading_date DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return list(reversed(rows))

def add_meter_reading(reading_date: str, main_kwh: float, sub_kwh: float, notes: str = ""):
    diff_kwh = round(main_kwh - sub_kwh, 2)
    diff_pct = round((diff_kwh / max(0.1, main_kwh)) * 100.0, 2)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO meter_readings (reading_date, main_meter_kwh, submeter_sum_kwh, difference_kwh, difference_pct, source, notes) VALUES (?, ?, ?, ?, ?, 'manual', ?)",
                (reading_date, main_kwh, sub_kwh, diff_kwh, diff_pct, notes))
    conn.commit()
    conn.close()

def get_all_alerts():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM alerts ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def resolve_alert(alert_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE alerts SET is_resolved = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

def get_restriction_logs(limit: int = 30):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM restriction_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ==============================================================================
# SECTION 2: ELECTRICAL CALCULATIONS & AC CIRCUITS
# ==============================================================================

NOMINAL_VOLTAGE_V = 230.0

def calculate_current(power_watts: float, voltage: float = NOMINAL_VOLTAGE_V, pf: float = 0.95) -> float:
    if voltage <= 0 or pf <= 0:
        return 0.0
    return round(float(power_watts) / (voltage * pf), 3)

def calculate_energy_kwh(power_watts: float, hours: float) -> float:
    return round((max(0.0, float(power_watts)) * max(0.0, float(hours))) / 1000.0, 4)

def simulate_variable_load_power(rated_watts: float, load_type: str = "constant", level: str = "normal") -> float:
    if load_type == "compressor_cycle":
        if level == "eco":
            return round(rated_watts * 0.55, 1)
        elif level == "high":
            return round(rated_watts * 1.10, 1)
        elif level == "standby":
            return round(max(5.0, rated_watts * 0.05), 1)
        return round(rated_watts * 0.75, 1)
    return round(rated_watts, 1)

def calculate_household_instantaneous_load(appliances: List[Dict[str, Any]], voltage: float = NOMINAL_VOLTAGE_V, wire_loss_pct: float = 1.2):
    total_app_w = 0.0
    active_count = 0
    junction_loads = {}

    for app in appliances:
        if bool(app.get("is_on", 1)) and not bool(app.get("is_restricted", 0)):
            w = float(app.get("actual_watts", app.get("rated_watts", 0.0)))
            jid = app.get("junction_id", "junc_other")
            total_app_w += w
            active_count += 1
            if jid not in junction_loads:
                junction_loads[jid] = {"watts": 0.0, "device_count": 0}
            junction_loads[jid]["watts"] += w
            junction_loads[jid]["device_count"] += 1

    line_loss_w = round(total_app_w * (wire_loss_pct / 100.0), 2)
    main_meter_w = round(total_app_w + line_loss_w, 2)
    main_amps = calculate_current(main_meter_w, voltage, 0.95)

    return {
        "active_devices_count": active_count,
        "total_devices_count": len(appliances),
        "total_appliance_watts": total_app_w,
        "distribution_loss_watts": line_loss_w,
        "main_meter_watts": main_meter_w,
        "main_meter_kw": round(main_meter_w / 1000.0, 3),
        "voltage_volts": voltage,
        "main_current_amps": main_amps,
        "combined_power_factor": 0.95,
        "junction_loads": junction_loads
    }


# ==============================================================================
# SECTION 3: OFFICIAL INDIAN TARIFF SYSTEM
# ==============================================================================

INDIAN_TARIFF_DATABASE = {
    "Maharashtra - MSEDCL": {
        "state": "Maharashtra",
        "discom": "MSEDCL (Mahavitaran)",
        "category": "LT-I Domestic",
        "effective_date": "2024-04-01",
        "verification_date": "2024-10-15",
        "source_ref": "MERC Tariff Order Case 226 of 2022",
        "is_official": True,
        "slabs": [
            {"from": 0, "to": 100, "rate": 5.88, "desc": "0 - 100 units"},
            {"from": 101, "to": 300, "rate": 11.26, "desc": "101 - 300 units"},
            {"from": 301, "to": 500, "rate": 15.72, "desc": "301 - 500 units"},
            {"from": 501, "to": None, "rate": 17.81, "desc": "> 500 units"}
        ],
        "fixed_charge": 128.0,
        "wheeling_charge_per_kwh": 1.38,
        "fppca_per_kwh": 0.45,
        "electricity_duty_pct": 16.0,
        "subsidy_eligible": False
    },
    "Delhi - BSES Rajdhani (BRPL)": {
        "state": "Delhi",
        "discom": "BSES Rajdhani Power Ltd.",
        "category": "Domestic 1-Phase",
        "effective_date": "2024-04-01",
        "verification_date": "2024-09-20",
        "source_ref": "DERC Tariff Schedule FY 2024-25",
        "is_official": True,
        "slabs": [
            {"from": 0, "to": 200, "rate": 3.00, "desc": "0 - 200 units"},
            {"from": 201, "to": 400, "rate": 4.50, "desc": "201 - 400 units"},
            {"from": 401, "to": 800, "rate": 6.50, "desc": "401 - 800 units"},
            {"from": 801, "to": 1200, "rate": 7.00, "desc": "801 - 1200 units"},
            {"from": 1201, "to": None, "rate": 8.00, "desc": "> 1200 units"}
        ],
        "fixed_charge": 40.0,
        "wheeling_charge_per_kwh": 0.0,
        "fppca_per_kwh": 0.0,
        "ppac_pct": 8.75,
        "regulatory_surcharge_pct": 8.0,
        "pension_surcharge_pct": 7.0,
        "electricity_duty_pct": 5.0,
        "subsidy_eligible": True,
        "subsidy_rules": {"type": "delhi_govt", "zero_threshold": 200, "fifty_pct_threshold": 400, "max_subsidy_amount": 800.0}
    },
    "Karnataka - BESCOM": {
        "state": "Karnataka",
        "discom": "Bangalore Electricity Supply Co.",
        "category": "LT-2(a) Domestic",
        "effective_date": "2024-05-01",
        "verification_date": "2024-10-01",
        "source_ref": "KERC Tariff Order 2024",
        "is_official": True,
        "slabs": [
            {"from": 0, "to": 100, "rate": 4.75, "desc": "0 - 100 units"},
            {"from": 101, "to": None, "rate": 7.00, "desc": "> 100 units"}
        ],
        "fixed_charge": 110.0,
        "wheeling_charge_per_kwh": 0.0,
        "fppca_per_kwh": 0.37,
        "electricity_duty_pct": 9.0,
        "subsidy_eligible": True,
        "subsidy_rules": {"type": "gruha_jyothi", "max_entitled_units": 200}
    },
    "Tamil Nadu - TANGEDCO": {
        "state": "Tamil Nadu",
        "discom": "TANGEDCO",
        "category": "LT Tariff I-A",
        "effective_date": "2024-07-01",
        "verification_date": "2024-09-15",
        "source_ref": "TNERC Tariff Order 2024",
        "is_official": True,
        "slabs": [
            {"from": 0, "to": 100, "rate": 0.00, "desc": "0 - 100 units (100% Subsidized)"},
            {"from": 101, "to": 200, "rate": 4.60, "desc": "101 - 200 units"},
            {"from": 201, "to": 400, "rate": 6.15, "desc": "201 - 400 units"},
            {"from": 401, "to": None, "rate": 8.20, "desc": "> 400 units"}
        ],
        "fixed_charge": 50.0,
        "wheeling_charge_per_kwh": 0.0,
        "fppca_per_kwh": 0.25,
        "electricity_duty_pct": 5.0,
        "subsidy_eligible": True
    },
    "Uttar Pradesh - UPPCL": {
        "state": "Uttar Pradesh",
        "discom": "UPPCL (Urban Domestic)",
        "category": "LMV-1 Domestic",
        "effective_date": "2024-04-01",
        "verification_date": "2024-08-30",
        "source_ref": "UPERC Tariff Order LMV-1",
        "is_official": True,
        "slabs": [
            {"from": 0, "to": 150, "rate": 5.50, "desc": "0 - 150 units"},
            {"from": 151, "to": 300, "rate": 6.00, "desc": "151 - 300 units"},
            {"from": 301, "to": 500, "rate": 6.50, "desc": "301 - 500 units"},
            {"from": 501, "to": None, "rate": 7.00, "desc": "> 500 units"}
        ],
        "fixed_charge": 110.0,
        "wheeling_charge_per_kwh": 0.0,
        "fppca_per_kwh": 0.30,
        "electricity_duty_pct": 5.0,
        "subsidy_eligible": False
    },
    "Illustrative Default / Custom": {
        "state": "Custom / General",
        "discom": "Demonstration DISCOM",
        "category": "Benchmark Domestic",
        "effective_date": "2024-01-01",
        "verification_date": "2024-01-01",
        "source_ref": "Demonstration benchmark 3-tier tariff",
        "is_official": False,
        "slabs": [
            {"from": 0, "to": 100, "rate": 4.50, "desc": "0 - 100 units"},
            {"from": 101, "to": 300, "rate": 7.50, "desc": "101 - 300 units"},
            {"from": 301, "to": None, "rate": 10.00, "desc": "> 300 units"}
        ],
        "fixed_charge": 100.0,
        "wheeling_charge_per_kwh": 0.0,
        "fppca_per_kwh": 0.30,
        "electricity_duty_pct": 5.0,
        "subsidy_eligible": False
    }
}

def get_available_tariffs():
    return list(INDIAN_TARIFF_DATABASE.keys())

def calculate_detailed_bill(units_kwh: float, tariff_key: str = "Maharashtra - MSEDCL", sanctioned_load_kw: float = 4.0, apply_subsidy: bool = True):
    tariff = INDIAN_TARIFF_DATABASE.get(tariff_key, INDIAN_TARIFF_DATABASE["Maharashtra - MSEDCL"])
    units = max(0.0, float(units_kwh))
    slabs = tariff.get("slabs", [])

    slab_breakdown = []
    total_energy_charges = 0.0
    remaining_units = units

    for slab in slabs:
        s_from = slab["from"]
        s_to = slab["to"]
        rate = float(slab["rate"])
        desc = slab.get("desc", f"{s_from} - {s_to if s_to else 'above'}")

        if s_to is None:
            units_in_slab = max(0.0, remaining_units)
        else:
            capacity = s_to - s_from + (1 if s_from > 0 else 0)
            units_in_slab = min(max(0.0, remaining_units), capacity)

        amount = round(units_in_slab * rate, 2)
        total_energy_charges += amount
        remaining_units = max(0.0, remaining_units - units_in_slab)

        slab_breakdown.append({
            "slab_desc": desc,
            "rate": rate,
            "units": round(units_in_slab, 2),
            "amount": amount
        })
        if remaining_units <= 0:
            break

    fixed_charges = float(tariff.get("fixed_charge", 100.0))
    wheeling = round(units * float(tariff.get("wheeling_charge_per_kwh", 0.0)), 2)
    fppca = round(units * float(tariff.get("fppca_per_kwh", 0.0)), 2)
    ppac = round((total_energy_charges + fixed_charges) * (float(tariff.get("ppac_pct", 0.0)) / 100.0), 2)
    surcharges = round((total_energy_charges + fixed_charges) * ((float(tariff.get("regulatory_surcharge_pct", 0.0)) + float(tariff.get("pension_surcharge_pct", 0.0))) / 100.0), 2)

    subtotal = total_energy_charges + fixed_charges + wheeling + fppca + ppac + surcharges
    duty_pct = float(tariff.get("electricity_duty_pct", 5.0))
    electricity_duty = round(subtotal * (duty_pct / 100.0), 2)
    gross_bill = round(subtotal + electricity_duty, 2)

    subsidy_amount = 0.0
    subsidy_desc = "None"
    if apply_subsidy and tariff.get("subsidy_eligible", False):
        rules = tariff.get("subsidy_rules", {})
        if rules.get("type") == "delhi_govt":
            if units <= rules.get("zero_threshold", 200):
                subsidy_amount = gross_bill
                subsidy_desc = "Delhi 100% Free Scheme (<=200 units)"
            elif units <= rules.get("fifty_pct_threshold", 400):
                subsidy_amount = min(round(gross_bill * 0.50, 2), float(rules.get("max_subsidy_amount", 800.0)))
                subsidy_desc = "Delhi 50% Subsidy"
        elif rules.get("type") == "gruha_jyothi" and units <= rules.get("max_entitled_units", 200):
            subsidy_amount = min(gross_bill, total_energy_charges + fixed_charges)
            subsidy_desc = "Karnataka Gruha Jyothi Free Power"

    net_bill = max(0.0, round(gross_bill - subsidy_amount, 2))
    eff_rate = round(net_bill / max(0.1, units), 2) if units > 0 else 0.0

    return {
        "state": tariff.get("state"),
        "discom": tariff.get("discom"),
        "category": tariff.get("category"),
        "effective_date": tariff.get("effective_date"),
        "verification_date": tariff.get("verification_date"),
        "source_ref": tariff.get("source_ref"),
        "is_official": tariff.get("is_official", True),
        "units_consumed": units,
        "slab_breakdown": slab_breakdown,
        "total_energy_charges": total_energy_charges,
        "fixed_charges": fixed_charges,
        "wheeling_charges": wheeling,
        "fppca_charges": fppca,
        "total_adjustments": round(wheeling + fppca + ppac + surcharges, 2),
        "electricity_duty": electricity_duty,
        "duty_pct": duty_pct,
        "gross_bill": gross_bill,
        "subsidy_amount": subsidy_amount,
        "subsidy_applied_desc": subsidy_desc,
        "net_bill": net_bill,
        "effective_rate_per_kwh": eff_rate
    }


# ==============================================================================
# SECTION 4: CIRCUIT GRAPH & TOPOLOGY (NetworkX + Plotly)
# ==============================================================================

def render_circuit_diagram(junctions: List[Dict[str, Any]], appliances: List[Dict[str, Any]], voltage: float = 230.0):
    G = nx.DiGraph()
    pos = {}
    node_meta = {}

    G.add_node("grid_supply")
    pos["grid_supply"] = (0.0, 0.5)
    node_meta["grid_supply"] = {"title": "Grid Power Supply", "type": "grid"}

    G.add_node("main_meter")
    pos["main_meter"] = (1.0, 0.5)
    G.add_edge("grid_supply", "main_meter", active=True)
    node_meta["main_meter"] = {"title": "Smart Main Meter", "type": "meter"}

    G.add_node("main_db")
    pos["main_db"] = (2.0, 0.5)
    G.add_edge("main_meter", "main_db", active=True)
    node_meta["main_db"] = {"title": "Main Distribution Board", "type": "db"}

    num_juncs = max(1, len(junctions))
    spacing = 1.0 / (num_juncs + 1)
    junc_y = {}

    for idx, junc in enumerate(junctions):
        jid = junc["id"]
        y = 1.0 - (idx + 1) * spacing
        junc_y[jid] = y
        G.add_node(jid)
        pos[jid] = (3.2, y)
        G.add_edge("main_db", jid, active=False)
        node_meta[jid] = {"title": junc["name"], "type": "junction", "active_w": 0.0, "icon": junc.get("icon", "⚡")}

    junc_apps = {}
    for app in appliances:
        junc_apps.setdefault(app["junction_id"], []).append(app)

    tot_w = 0.0
    for jid, apps in junc_apps.items():
        base_y = junc_y.get(jid, 0.5)
        num_a = len(apps)
        spread = 0.12 * max(1, num_a - 1)
        start_y = base_y + spread / 2.0
        y_step = spread / max(1, num_a - 1) if num_a > 1 else 0.0

        for a_idx, app in enumerate(apps):
            aid = app["id"]
            app_y = start_y - (a_idx * y_step) if num_a > 1 else base_y
            is_on = bool(app.get("is_on", 1))
            is_restr = bool(app.get("is_restricted", 0))

            eff_w = float(app.get("actual_watts", 0.0)) if (is_on and not is_restr) else 0.0
            tot_w += eff_w

            status_str = "RESTRICTED" if is_restr else ("ON" if is_on else "OFF")
            G.add_node(aid)
            pos[aid] = (4.8, app_y)
            is_act = (is_on and not is_restr)
            G.add_edge(jid, aid, active=is_act)

            if is_act and jid in node_meta:
                node_meta[jid]["active_w"] += eff_w
                if G.has_edge("main_db", jid):
                    G["main_db"][jid]["active"] = True

            node_meta[aid] = {
                "title": app["name"],
                "type": "appliance",
                "status": status_str,
                "watts": eff_w,
                "rated": app.get("rated_watts", 0.0)
            }

    fig = go.Figure()

    # Draw Edges
    edge_x_inact, edge_y_inact = [], []
    edge_x_act, edge_y_act = [], []

    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        if data.get("active", False):
            edge_x_act.extend([x0, x1, None])
            edge_y_act.extend([y0, y1, None])
        else:
            edge_x_inact.extend([x0, x1, None])
            edge_y_inact.extend([y0, y1, None])

    if edge_x_inact:
        fig.add_trace(go.Scatter(x=edge_x_inact, y=edge_y_inact, line=dict(width=1.5, color='#CBD5E1', dash='dot'), hoverinfo='none', mode='lines', name='Idle Circuit'))
    if edge_x_act:
        fig.add_trace(go.Scatter(x=edge_x_act, y=edge_y_act, line=dict(width=3.5, color='#0D9488'), hoverinfo='none', mode='lines', name='Active Power Flow'))

    # Node groupings
    categories = {
        "grid": {"nodes": [], "x": [], "y": [], "color": "#D97706", "symbol": "diamond-wide", "size": 24, "name": "Grid Supply"},
        "meter": {"nodes": [], "x": [], "y": [], "color": "#2563EB", "symbol": "circle", "size": 26, "name": "Smart Meter"},
        "db": {"nodes": [], "x": [], "y": [], "color": "#1E293B", "symbol": "square", "size": 24, "name": "Main DB"},
        "junction": {"nodes": [], "x": [], "y": [], "color": "#0284C7", "symbol": "hexagon", "size": 22, "name": "Junctions"},
        "app_on": {"nodes": [], "x": [], "y": [], "color": "#10B981", "symbol": "circle", "size": 18, "name": "Device ON"},
        "app_off": {"nodes": [], "x": [], "y": [], "color": "#94A3B8", "symbol": "circle", "size": 16, "name": "Device OFF"},
        "app_restr": {"nodes": [], "x": [], "y": [], "color": "#EF4444", "symbol": "x", "size": 20, "name": "RESTRICTED"}
    }

    hover_map = {}
    label_map = {}

    for n in G.nodes():
        x, y = pos[n]
        meta = node_meta.get(n, {})
        nt = meta.get("type")
        st = meta.get("status")

        if nt == "grid":
            cat = "grid"
            lbl = "⚡ Grid Supply"
            hover = "<b>230V AC Mains</b> (50 Hz Single Phase)"
        elif nt == "meter":
            cat = "meter"
            lbl = "📊 Smart Meter"
            hover = f"<b>Smart Main Meter</b><br>Load: {tot_w:.0f} W"
        elif nt == "db":
            cat = "db"
            lbl = "🎛️ Main DB"
            hover = "<b>Main Distribution Board</b>"
        elif nt == "junction":
            cat = "junction"
            lbl = f"{meta.get('icon','⚡')} {meta.get('title')}"
            hover = f"<b>{meta.get('title')}</b><br>Active: {meta.get('active_w', 0):.0f} W"
        elif nt == "appliance":
            if st == "RESTRICTED":
                cat = "app_restr"
                lbl = f"⛔ {meta.get('title')}"
                hover = f"<b>{meta.get('title')}</b> [RESTRICTED]"
            elif st == "ON":
                cat = "app_on"
                lbl = f"🟢 {meta.get('title')}"
                hover = f"<b>{meta.get('title')}</b><br>Load: {meta.get('watts', 0):.0f} W"
            else:
                cat = "app_off"
                lbl = f"⚪ {meta.get('title')}"
                hover = f"<b>{meta.get('title')}</b> [OFF]"
        else:
            cat = "app_off"
            lbl, hover = n, n

        categories[cat]["nodes"].append(n)
        categories[cat]["x"].append(x)
        categories[cat]["y"].append(y)
        hover_map[n] = hover
        label_map[n] = lbl

    for cat_k, cdata in categories.items():
        if cdata["nodes"]:
            fig.add_trace(go.Scatter(
                x=cdata["x"], y=cdata["y"],
                mode='markers+text',
                marker=dict(symbol=cdata["symbol"], size=cdata["size"], color=cdata["color"], line=dict(width=2, color='#FFFFFF')),
                text=[label_map[n] for n in cdata["nodes"]],
                textposition="middle right" if "app" in cat_k else "bottom center",
                textfont=dict(size=11, family="Inter, sans-serif"),
                hoverinfo='text',
                hovertext=[hover_map[n] for n in cdata["nodes"]],
                name=cdata["name"]
            ))

    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.22, xanchor="center", x=0.5),
        margin=dict(l=20, r=160, t=30, b=70),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.4, 6.2]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.15, 1.15]),
        plot_bgcolor="#F8FAFC",
        height=600
    )
    return fig


# ==============================================================================
# SECTION 5: BILL HIKE ANALYZER & DISCREPANCY ENGINES
# ==============================================================================

def analyze_bill_hike(current_kwh: float, prev_kwh: float, tariff_key: str = "Maharashtra - MSEDCL", sanctioned_load_kw: float = 4.0, curr_apps=None, prev_apps=None):
    curr_c = calculate_detailed_bill(current_kwh, tariff_key, sanctioned_load_kw)
    prev_c = calculate_detailed_bill(prev_kwh, tariff_key, sanctioned_load_kw)

    k_diff = round(current_kwh - prev_kwh, 2)
    k_pct = round((k_diff / max(0.1, prev_kwh)) * 100.0, 1)
    b_diff = round(curr_c["net_bill"] - prev_c["net_bill"], 2)
    b_pct = round((b_diff / max(0.1, prev_c["net_bill"])) * 100.0, 1)

    confirmed = []
    if k_diff > 0:
        confirmed.append(f"Consumption grew by **+{k_diff:.1f} kWh ({k_pct:+.1f}%)**, rising from {prev_kwh:.1f} to {current_kwh:.1f} kWh.")
    else:
        confirmed.append(f"Consumption decreased by **{abs(k_diff):.1f} kWh**, lowering base energy charges.")

    possible = [
        "Summer/Monsoon climate changes: Inverter compressors draw elevated runtime during high ambient temperatures.",
        "Telescopic slab penalty: Extra units consumed in high slabs cost up to 2.5x more than base tier units."
    ]
    actions = [
        "Set AC thermostat to 24°C–26°C instead of 18°C–20°C (saves ~6% per degree).",
        "Put storage geysers on a 20-minute morning timer rather than leaving active all day.",
        "Set a monthly limit alert in WattWise before crossing higher tariff slabs."
    ]

    return {
        "current_bill": curr_c["net_bill"],
        "previous_bill": prev_c["net_bill"],
        "kwh_diff": k_diff,
        "kwh_pct": k_pct,
        "bill_diff": b_diff,
        "bill_pct": b_pct,
        "variance_breakdown": {
            "energy_charges": round(curr_c["total_energy_charges"] - prev_c["total_energy_charges"], 2),
            "fixed_charges": round(curr_c["fixed_charges"] - prev_c["fixed_charges"], 2),
            "surcharges_and_fuel": round(curr_c["total_adjustments"] - prev_c["total_adjustments"], 2),
            "taxes_and_duty": round(curr_c["electricity_duty"] - prev_c["electricity_duty"], 2),
            "subsidy_change": round(prev_c["subsidy_amount"] - curr_c["subsidy_amount"], 2)
        },
        "confirmed_reasons": confirmed,
        "possible_explanations": possible,
        "action_items": actions
    }

def perform_discrepancy_check(main_kwh: float, sub_kwh: float, tolerance_pct: float = 3.0, wire_loss_pct: float = 1.2):
    diff_kwh = round(main_kwh - sub_kwh, 3)
    diff_pct = round((diff_kwh / max(0.1, main_kwh)) * 100.0, 2)
    exp_loss = round(sub_kwh * (wire_loss_pct / 100.0), 3)
    unexplained_kwh = round(diff_kwh - exp_loss, 3)
    unexp_pct = round((unexplained_kwh / max(0.1, main_kwh)) * 100.0, 2)

    if abs(unexp_pct) <= tolerance_pct:
        status, color = "HEALTHY", "#10B981"
        msg = f"Reconciliation within acceptable tolerance (±{tolerance_pct}%)."
    elif unexp_pct > tolerance_pct and unexp_pct <= (tolerance_pct * 2.5):
        status, color = "ELEVATED_LOSS", "#F59E0B"
        msg = f"Main meter records {diff_pct}% higher than branch submeters. Moderate discrepancy."
    else:
        status, color = "SIGNIFICANT_DISCREPANCY", "#EF4444"
        msg = f"Discrepancy of {diff_pct}% exceeds normal electrical tolerance thresholds."

    return {
        "main_meter_kwh": main_kwh,
        "submeter_sum_kwh": sub_kwh,
        "difference_kwh": diff_kwh,
        "difference_pct": diff_pct,
        "expected_wire_loss_kwh": exp_loss,
        "unexplained_kwh": unexplained_kwh,
        "unexplained_pct": unexp_pct,
        "health_status": status,
        "status_color": color,
        "summary_msg": msg
    }


# ==============================================================================
# SECTION 6: CHARTS GENERATION
# ==============================================================================

def create_power_gauge(current_watts: float, max_watts: float = 4000.0):
    kw = current_watts / 1000.0
    m_kw = max_watts / 1000.0
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=kw,
        title={'text': f"<b>Household Active Load</b><br><span style='font-size:12px;color:#64748B;'>{current_watts:.0f} W</span>"},
        number={'suffix': " kW", 'font': {'size': 26}},
        gauge={
            'axis': {'range': [0, m_kw]},
            'bar': {'color': "#0D9488" if kw < (m_kw * 0.75) else "#EF4444"},
            'steps': [
                {'range': [0, m_kw * 0.6], 'color': "#E0F2FE"},
                {'range': [m_kw * 0.6, m_kw * 0.85], 'color': "#FEF3C7"},
                {'range': [m_kw * 0.85, m_kw], 'color': "#FEE2E2"}
            ]
        }
    ))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=30, b=20))
    return fig

def create_daily_consumption_chart(daily_records: List[Dict[str, Any]], limit_kwh: float = 15.0):
    if not daily_records:
        fig = go.Figure()
        fig.add_annotation(text="No daily records", showarrow=False)
        return fig
    df = pd.DataFrame(daily_records)
    df["date"] = pd.to_datetime(df["date"])
    df["rolling"] = df["total_kwh"].rolling(7, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["date"], y=df["total_kwh"], name="Daily kWh", marker_color=["#EF4444" if k > limit_kwh else "#0D9488" for k in df["total_kwh"]]))
    fig.add_trace(go.Scatter(x=df["date"], y=df["rolling"], name="7-Day Avg", line=dict(color="#2563EB", width=2)))
    fig.add_hline(y=limit_kwh, line_dash="dash", line_color="#DC2626", annotation_text=f"Limit ({limit_kwh} kWh)")
    fig.update_layout(title="<b>Daily Energy Consumption (Last 30 Days)</b>", height=320, margin=dict(l=30, r=20, t=50, b=30), plot_bgcolor="#F8FAFC")
    return fig

def create_monthly_trends_chart(monthly_records: List[Dict[str, Any]]):
    if not monthly_records:
        return go.Figure()
    df = pd.DataFrame(monthly_records)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["month_str"], y=df["total_kwh"], name="kWh", marker_color="#0D9488", yaxis="y1"))
    fig.add_trace(go.Scatter(x=df["month_str"], y=df["total_bill"], name="Bill (₹)", line=dict(color="#2563EB", width=3), yaxis="y2"))
    fig.update_layout(
        title="<b>Historical Monthly Consumption & Electricity Bill</b>",
        yaxis=dict(title="kWh", side="left", color="#0D9488"),
        yaxis2=dict(title="Bill (₹)", side="right", overlaying="y", color="#2563EB"),
        height=320, margin=dict(l=30, r=40, t=50, b=30), plot_bgcolor="#F8FAFC"
    )
    return fig

def create_bill_waterfall_chart(analysis: Dict[str, Any]):
    vb = analysis["variance_breakdown"]
    x = ["Prev Month", "Energy Slabs", "Fixed Charges", "Surcharges/Fuel", "Duty & Taxes", "Subsidy Δ", "Current Month"]
    y = [analysis["previous_bill"], vb["energy_charges"], vb["fixed_charges"], vb["surcharges_and_fuel"], vb["taxes_and_duty"], vb["subsidy_change"], analysis["current_bill"]]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=["absolute", "relative", "relative", "relative", "relative", "relative", "total"],
        x=x, y=y, text=[f"₹{abs(v):.0f}" for v in y], textposition="outside",
        decreasing={"marker": {"color": "#10B981"}}, increasing={"marker": {"color": "#EF4444"}}
    ))
    fig.update_layout(title="<b>Bill Variance Cost Bridge (₹)</b>", height=330, margin=dict(l=30, r=20, t=50, b=30), plot_bgcolor="#F8FAFC")
    return fig


# ==============================================================================
# SECTION 7: STREAMLIT APP INITIALIZATION & NAVIGATION
# ==============================================================================

init_database()
seed_default_data_if_empty()
seed_realistic_historical_data()

st.set_page_config(page_title="WattWise — Smart Electricity Meter Simulator", page_icon="⚡", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .metric-card { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 12px; }
    .metric-title { color: #64748B; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; margin-bottom: 6px; }
    .metric-value { color: #0F172A; font-size: 1.75rem; font-weight: 700; line-height: 1.2; }
    .metric-sub { font-size: 0.8rem; color: #64748B; margin-top: 4px; }
    .badge-on { background-color: #DCFCE7; color: #166534; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
    .badge-off { background-color: #F1F5F9; color: #64748B; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
    .badge-restr { background-color: #FEE2E2; color: #991B1B; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
    .alert-banner { border-left: 4px solid #EF4444; background-color: #FEF2F2; padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; color: #991B1B; }
</style>
""", unsafe_allow_html=True)

# Fetch data
junctions = get_all_junctions()
appliances = get_all_appliances()
limits = get_energy_limits()
settings = get_app_settings()
monthly_summaries = get_monthly_summaries()
daily_summaries = get_daily_summaries(limit_days=30)

tariff_key = settings.get("selected_state_tariff", "Maharashtra - MSEDCL")
sanctioned_load_kw = float(settings.get("sanctioned_load_kw", 4.0))
wire_loss_pct = float(settings.get("wire_loss_pct", 1.2))

load_state = calculate_household_instantaneous_load(appliances, 230.0, wire_loss_pct)
curr_month_kwh = monthly_summaries[-1]["total_kwh"] if monthly_summaries else 320.0
prev_month_kwh = monthly_summaries[-2]["total_kwh"] if len(monthly_summaries) >= 2 else 280.0
today_kwh = daily_summaries[-1]["total_kwh"] if daily_summaries else 11.4

curr_bill = calculate_detailed_bill(curr_month_kwh, tariff_key, sanctioned_load_kw)
prev_bill = calculate_detailed_bill(prev_month_kwh, tariff_key, sanctioned_load_kw)

# Sidebar
st.sidebar.markdown("""
<div style="padding: 10px 0 15px 0;">
    <h2 style="margin: 0; color: #0F172A; font-weight: 800;">⚡ WattWise</h2>
    <span style="font-size: 0.8rem; color: #0D9488; font-weight: 600;">SMART METER SIMULATOR</span>
</div>
""", unsafe_allow_html=True)

nav = st.sidebar.radio("Navigation", [
    "📊 Dashboard", "⚡ Live Circuit", "🔌 My Appliances", "🎛️ Junction Monitor",
    "📈 Energy Analytics", "📜 Electricity Bill", "🔍 Bill Hike Analyzer",
    "🩺 Meter Health", "🛡️ Energy Limits", "🔔 Alerts Center", "📥 Reports & Export", "⚙️ Settings"
])

st.sidebar.markdown("---")
st.sidebar.markdown(f"""
<div style="background: #F1F5F9; border-radius: 8px; padding: 12px;">
    <div style="font-size: 0.75rem; color: #64748B; font-weight: 600;">ACTIVE GRID LOAD</div>
    <div style="font-size: 1.3rem; font-weight: 700; color: #0D9488;">{load_state['main_meter_watts']:.0f} W</div>
    <div style="font-size: 0.75rem; color: #475569;">Active Devices: <b>{load_state['active_devices_count']} / {load_state['total_devices_count']}</b></div>
</div>
""", unsafe_allow_html=True)


# ==============================================================================
# PAGE 1: DASHBOARD
# ==============================================================================
if nav == "📊 Dashboard":
    st.title("Smart Electricity Meter Dashboard")
    st.caption("Real-time simulated power distribution, daily energy pacing, and transparent cost telemetry.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="metric-card"><div class="metric-title">Instantaneous Load</div><div class="metric-value" style="color:#0D9488;">{load_state["main_meter_watts"]:.0f} W</div><div class="metric-sub">Line Current: <b>{load_state["main_current_amps"]:.2f} A</b> @ 230V</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><div class="metric-title">Today\'s Energy</div><div class="metric-value">{today_kwh:.2f} kWh</div><div class="metric-sub">Est. Cost: <b>₹{today_kwh * curr_bill["effective_rate_per_kwh"]:.2f}</b></div></div>', unsafe_allow_html=True)
    with c3:
        k_pct = round(((curr_month_kwh - prev_month_kwh) / max(0.1, prev_month_kwh)) * 100, 1)
        st.markdown(f'<div class="metric-card"><div class="metric-title">Current Month</div><div class="metric-value">{curr_month_kwh:.1f} kWh</div><div class="metric-sub"><b>{"+" if k_pct>0 else ""}{k_pct}%</b> vs Last Month</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="metric-card"><div class="metric-title">Estimated Monthly Bill</div><div class="metric-value" style="color:#2563EB;">₹{curr_bill["net_bill"]:.2f}</div><div class="metric-sub">Tariff: <b>{curr_bill["state"]}</b></div></div>', unsafe_allow_html=True)

    g_col, d_col = st.columns([1, 2])
    with g_col:
        st.plotly_chart(create_power_gauge(load_state["main_meter_watts"], max_watts=sanctioned_load_kw * 1000.0), use_container_width=True)
    with d_col:
        st.plotly_chart(create_daily_consumption_chart(daily_summaries, limit_kwh=float(limits.get("daily_kwh_limit", 15.0))), use_container_width=True)

    st.plotly_chart(create_monthly_trends_chart(monthly_summaries), use_container_width=True)


# ==============================================================================
# PAGE 2: LIVE CIRCUIT
# ==============================================================================
elif nav == "⚡ Live Circuit":
    st.title("Live Household Circuit Topology")
    st.caption("Interactive visual simulation: Grid Supply ➔ Smart Meter ➔ Main DB ➔ Branch Junctions ➔ Appliances.")

    st.plotly_chart(render_circuit_diagram(junctions, appliances, 230.0), use_container_width=True)

    st.subheader("⚡ Quick Device Power Controls")
    cols = st.columns(3)
    for idx, app in enumerate(appliances):
        aid = app["id"]
        is_on = bool(app.get("is_on", 1))
        is_restr = bool(app.get("is_restricted", 0))
        with cols[idx % 3]:
            with st.container(border=True):
                st.markdown(f"**{app['name']}**")
                st.caption(f"Rated: {app.get('rated_watts')} W | Actual: {app.get('actual_watts')} W")
                if is_restr:
                    st.markdown('<span class="badge-restr">RESTRICTED</span>', unsafe_allow_html=True)
                    if st.button("Unlock 🔓", key=f"unl_{aid}"):
                        update_appliance_state(aid, 1)
                        st.rerun()
                else:
                    if is_on:
                        st.markdown('<span class="badge-on">ON</span>', unsafe_allow_html=True)
                        if st.button("Turn OFF ⏹️", key=f"t_off_{aid}"):
                            update_appliance_state(aid, 0)
                            st.rerun()
                    else:
                        st.markdown('<span class="badge-off">OFF</span>', unsafe_allow_html=True)
                        if st.button("Turn ON ▶️", key=f"t_on_{aid}"):
                            update_appliance_state(aid, 1)
                            st.rerun()


# ==============================================================================
# PAGE 3: MY APPLIANCES
# ==============================================================================
elif nav == "🔌 My Appliances":
    st.title("Appliance Inventory & Management")
    for app in appliances:
        aid = app["id"]
        is_on = bool(app.get("is_on", 1))
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            with c1:
                st.markdown(f"### {app['name']}")
                st.caption(f"Category: {app.get('category')} | Hours: {app.get('daily_hours')} hrs/day")
            with c2:
                st.markdown(f"**Rated:** {app.get('rated_watts'):.0f} W")
                st.markdown(f"**Actual:** {app.get('actual_watts'):.0f} W")
            with c3:
                daily_k = calculate_energy_kwh(app.get('actual_watts', 0) if is_on else 0, app.get('daily_hours', 4))
                st.markdown(f"**Daily kWh:** {daily_k:.2f}")
                st.markdown(f"**Monthly Est:** {daily_k * 30:.1f} kWh")
            with c4:
                if st.button("Turn OFF" if is_on else "Turn ON", key=f"app_b_{aid}"):
                    update_appliance_state(aid, 0 if is_on else 1)
                    st.rerun()


# ==============================================================================
# PAGE 4: JUNCTION MONITOR
# ==============================================================================
elif nav == "🎛️ Junction Monitor":
    st.title("Branch Junction Monitoring")
    jdata = []
    for j in junctions:
        j_apps = [a for a in appliances if a["junction_id"] == j["id"]]
        act_w = sum(float(a.get("actual_watts", 0)) for a in j_apps if a.get("is_on") and not a.get("is_restricted"))
        cap = float(j.get("max_capacity_watts", 4000.0))
        jdata.append({
            "Junction": f"{j.get('icon', '⚡')} {j['name']}",
            "Connected Devices": len(j_apps),
            "Active Load (W)": act_w,
            "Capacity (W)": cap,
            "Utilization (%)": round((act_w / cap) * 100, 1)
        })
    st.dataframe(pd.DataFrame(jdata), use_container_width=True, hide_index=True)


# ==============================================================================
# PAGE 5: ENERGY ANALYTICS
# ==============================================================================
elif nav == "📈 Energy Analytics":
    st.title("Energy Analytics & Trends")
    st.plotly_chart(create_daily_consumption_chart(daily_summaries), use_container_width=True)
    st.plotly_chart(create_monthly_trends_chart(monthly_summaries), use_container_width=True)


# ==============================================================================
# PAGE 6: ELECTRICITY BILL
# ==============================================================================
elif nav == "📜 Electricity Bill":
    st.title("Indian State Electricity Tariff & Bill Breakdown")
    b1, b2 = st.columns([1, 2])
    with b1:
        st.subheader("Tariff Configuration")
        sel_t = st.selectbox("Select State & DISCOM", get_available_tariffs(), index=0)
        u_inp = st.number_input("Units Consumed (kWh)", value=float(curr_month_kwh), step=10.0)
        load_inp = st.number_input("Sanctioned Load (kW)", value=sanctioned_load_kw, step=1.0)
        bill_out = calculate_detailed_bill(u_inp, sel_t, load_inp)

    with b2:
        st.markdown(f"""
        <div style="background:#0F172A; color:#FFFFFF; border-radius:12px; padding:20px; margin-bottom:15px;">
            <div style="font-size:0.85rem; color:#94A3B8;">FINAL ESTIMATED NET BILL</div>
            <div style="font-size:2.4rem; font-weight:800; color:#38BDF8;">₹{bill_out['net_bill']:.2f}</div>
            <div>Average Rate: <b>₹{bill_out['effective_rate_per_kwh']:.2f} / kWh</b></div>
        </div>
        """, unsafe_allow_html=True)
        st.write("#### Telescopic Slab Breakdown")
        st.dataframe(pd.DataFrame(bill_out["slab_breakdown"]), use_container_width=True, hide_index=True)


# ==============================================================================
# PAGE 7: BILL HIKE ANALYZER
# ==============================================================================
elif nav == "🔍 Bill Hike Analyzer":
    st.title("Why Did My Electricity Bill Increase?")
    c1, c2 = st.columns(2)
    with c1:
        p_u = st.number_input("Previous Month Units", value=float(prev_month_kwh))
    with c2:
        c_u = st.number_input("Current Month Units", value=float(curr_month_kwh))

    hike = analyze_bill_hike(c_u, p_u, tariff_key, sanctioned_load_kw)
    st.plotly_chart(create_bill_waterfall_chart(hike), use_container_width=True)

    st.subheader("Attribution Summary")
    for cr in hike["confirmed_reasons"]:
        st.write(f"- {cr}")
    for act in hike["action_items"]:
        st.write(f"✓ {act}")


# ==============================================================================
# PAGE 8: METER HEALTH
# ==============================================================================
elif nav == "🩺 Meter Health":
    st.title("Meter Health & Discrepancy Diagnostics")
    c1, c2 = st.columns(2)
    with c1:
        m_val = st.number_input("Main Meter Reading (kWh)", value=float(curr_month_kwh * 1.018))
        s_val = st.number_input("Submeters Sum (kWh)", value=float(curr_month_kwh))
        tol = st.slider("Tolerance (%)", 1.0, 10.0, 3.0)
    health = perform_discrepancy_check(m_val, s_val, tol)
    with c2:
        st.markdown(f"""
        <div style="border:2px solid {health['status_color']}; border-radius:12px; padding:18px;">
            <div style="font-size:1.6rem; font-weight:800; color:{health['status_color']};">{health['health_status']}</div>
            <p>{health['summary_msg']}</p>
        </div>
        """, unsafe_allow_html=True)
        st.write(f"Difference: **{health['difference_kwh']:+.2f} kWh ({health['difference_pct']:+.1f}%)**")


# ==============================================================================
# PAGE 9: ENERGY LIMITS
# ==============================================================================
elif nav == "🛡️ Energy Limits":
    st.title("Smart Energy Budget & Restriction")
    st.write(f"Monthly Limit: **{limits.get('monthly_kwh_limit')} kWh** | Current: **{curr_month_kwh:.1f} kWh**")
    st.progress(min(1.0, curr_month_kwh / float(limits.get("monthly_kwh_limit", 400.0))))
    st.subheader("Restriction History")
    logs = get_restriction_logs()
    if logs:
        st.dataframe(pd.DataFrame(logs), use_container_width=True)
    else:
        st.info("No active restrictions.")


# ==============================================================================
# PAGE 10: ALERTS CENTER
# ==============================================================================
elif nav == "🔔 Alerts Center":
    st.title("Alerts & Notification Center")
    all_alerts = get_all_alerts()
    for a in all_alerts:
        with st.container(border=True):
            st.markdown(f"**[{a['severity']}] {a['title']}**")
            st.caption(f"{a['timestamp']}")
            st.write(a["message"])
            if not a.get("is_resolved"):
                if st.button("Resolve ✓", key=f"al_{a['id']}"):
                    resolve_alert(a["id"])
                    st.rerun()


# ==============================================================================
# PAGE 11: REPORTS & EXPORT
# ==============================================================================
elif nav == "📥 Reports & Export":
    st.title("Data Reports & Export")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Download Appliances CSV", data=pd.DataFrame(appliances).to_csv(index=False), file_name="WattWise_Appliances.csv", mime="text/csv")
    with c2:
        st.download_button("Download Monthly Summaries CSV", data=pd.DataFrame(monthly_summaries).to_csv(index=False), file_name="WattWise_Monthly.csv", mime="text/csv")


# ==============================================================================
# PAGE 12: SETTINGS
# ==============================================================================
elif nav == "⚙️ Settings":
    st.title("System & Simulation Settings")
    with st.form("settings_form"):
        name_inp = st.text_input("Consumer Name", settings.get("consumer_name", "Sanidhya Sharma"))
        load_inp = st.number_input("Sanctioned Load (kW)", value=sanctioned_load_kw)
        wire_loss = st.number_input("Wiring Loss (%)", value=wire_loss_pct)
        if st.form_submit_button("Save Settings"):
            update_app_setting("consumer_name", name_inp)
            update_app_setting("sanctioned_load_kw", str(load_inp))
            update_app_setting("wire_loss_pct", str(wire_loss))
            st.success("Settings saved successfully!")
            st.rerun()
