


from datetime import date, timedelta
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="SMARTGRID | Energy Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Theme ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: Inter, sans-serif; }
.stApp { background: radial-gradient(circle at 12% 0%, #122238 0%, #090d16 42%, #070a10 100%); color: #edf3ff; }
[data-testid="stSidebar"] { background: #0b111d; border-right: 1px solid #1d2a3d; }
.block-container { padding-top: 1.6rem; padding-bottom: 2.2rem; max-width: 1600px; }
h1, h2, h3 { color: #f3f7ff; letter-spacing: -0.03em; }
div[data-testid="stMetric"] { background: linear-gradient(145deg,#121e30,#0d1421); border: 1px solid #24344a; padding: 17px 18px; border-radius: 16px; }
div[data-testid="stMetricLabel"] { color: #9fb2cc; }
div[data-testid="stMetricValue"] { color: #f4f8ff; }
div[data-testid="stMetricDelta"] { color: #43e0b0; }
.stButton > button { border-radius: 10px; border: 1px solid #29415d; background: #132238; color: #eaf3ff; font-weight: 600; }
.stButton > button:hover { border-color: #39d8bc; color: white; }
div[data-testid="stDataFrame"] { border: 1px solid #24344a; border-radius: 12px; overflow: hidden; }
div[data-testid="stAlert"] { border-radius: 12px; }
hr { border-color: #1e2a3b; }
.small-muted { color: #92a5bf; font-size: 0.88rem; }
.hero { padding: 22px 24px; border: 1px solid #24344a; border-radius: 20px; background: linear-gradient(115deg,rgba(22,45,68,.95),rgba(14,22,37,.92)); margin-bottom: 18px; }
.pill { display:inline-block; padding:5px 10px; border-radius:999px; color:#56e6c1; background:#10312e; border:1px solid #1a5a50; font-size:12px; font-weight:700; letter-spacing:.06em; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="pill">● SIMULATION ONLINE</div>
  <h1 style="margin:12px 0 4px 0;font-size:2.45rem;">⚡ SMARTGRID <span style="color:#46dfc1;">ENERGY</span></h1>
  <div style="color:#a8bad2;font-size:1.02rem;">Appliance intelligence · Smart meter · Usage limits · Bill forecasting</div>
  <div class="small-muted" style="margin-top:12px;">Virtual junction → individual appliance channels → analytics and simulated relay controls</div>
</div>
""", unsafe_allow_html=True)

# ---------- Demo appliance model ----------
DEFAULT_APPLIANCES = [
    {"Appliance": "Air Conditioner", "Icon": "❄️", "Rated_W": 1500, "Avg_Hours_Day": 5.0, "Power_Factor": 0.92, "Limit_kWh": 8.0},
    {"Appliance": "Refrigerator", "Icon": "🧊", "Rated_W": 180, "Avg_Hours_Day": 9.0, "Power_Factor": 0.85, "Limit_kWh": 2.5},
    {"Appliance": "Water Heater", "Icon": "♨️", "Rated_W": 2000, "Avg_Hours_Day": 0.7, "Power_Factor": 1.00, "Limit_kWh": 3.0},
    {"Appliance": "Washing Machine", "Icon": "🫧", "Rated_W": 500, "Avg_Hours_Day": 0.8, "Power_Factor": 0.90, "Limit_kWh": 1.5},
    {"Appliance": "Laptop", "Icon": "💻", "Rated_W": 90, "Avg_Hours_Day": 6.0, "Power_Factor": 0.95, "Limit_kWh": 1.0},
    {"Appliance": "Lighting", "Icon": "💡", "Rated_W": 100, "Avg_Hours_Day": 6.0, "Power_Factor": 0.98, "Limit_kWh": 1.0},
    {"Appliance": "Ceiling Fan", "Icon": "🌀", "Rated_W": 70, "Avg_Hours_Day": 10.0, "Power_Factor": 0.90, "Limit_kWh": 1.2},
]

if "appliances" not in st.session_state:
    st.session_state.appliances = pd.DataFrame(DEFAULT_APPLIANCES)
if "enabled" not in st.session_state:
    st.session_state.enabled = {x["Appliance"]: True for x in DEFAULT_APPLIANCES}
if "locked" not in st.session_state:
    st.session_state.locked = {x["Appliance"]: False for x in DEFAULT_APPLIANCES}
if "usage_factor" not in st.session_state:
    st.session_state.usage_factor = {x["Appliance"]: 1.0 for x in DEFAULT_APPLIANCES}
if "seed" not in st.session_state:
    st.session_state.seed = 24

# ---------- Sidebar controls ----------
with st.sidebar:
    st.markdown("## ⚙️ Simulation setup")
    st.caption("Change the virtual circuit's operating conditions.")
    voltage = st.slider("Supply voltage (V)", 200, 250, 230)
    simulation_days = st.slider("History length (days)", 7, 90, 30)
    noise = st.slider("Usage variability (%)", 0, 40, 12)
    st.markdown("---")
    st.markdown("### 🧾 Bill settings")
    state_name = st.selectbox("State / tariff profile", [
        "Rajasthan — editable demo", "Delhi — editable demo", "Maharashtra — editable demo",
        "Gujarat — editable demo", "Uttar Pradesh — editable demo", "Custom tariff"
    ])
    discom = st.text_input("DISCOM / provider (optional)", value="Enter your local DISCOM")
    tariff_rate = st.number_input("Energy charge (₹/kWh)", min_value=0.0, max_value=100.0, value=7.0, step=0.25)
    fixed_charge = st.number_input("Monthly fixed charge (₹)", min_value=0.0, max_value=10000.0, value=150.0, step=25.0)
    other_pct = st.number_input("Other charges (%)", min_value=0.0, max_value=100.0, value=8.0, step=1.0)
    st.caption("Tariff values are editable placeholders, not verified live tariffs. Enter the current rate from your own bill / official DISCOM tariff order.")
    st.markdown("---")
    if st.button("↻ Regenerate simulation", use_container_width=True):
        st.session_state.seed += 1
        st.rerun()

# ---------- Generate deterministic simulated daily readings ----------
def make_history(appliances, days, seed, noise_pct, usage_factors, enabled, locked):
    rng = np.random.default_rng(seed)
    end = date.today()
    dates = [end - timedelta(days=i) for i in range(days - 1, -1, -1)]
    rows = []
    for _, a in appliances.iterrows():
        name = a["Appliance"]
        for d in dates:
            weekday_factor = 0.88 if d.weekday() >= 5 else 1.0
            random_factor = rng.normal(1.0, noise_pct / 100.0)
            hours = max(0.0, float(a["Avg_Hours_Day"]) * weekday_factor * random_factor * usage_factors.get(name, 1.0))
            is_on = bool(enabled.get(name, True)) and not bool(locked.get(name, False))
            if not is_on:
                hours = 0.0
            # Simulate an occasional usage spike to demonstrate anomaly detection.
            spike = False
            if rng.random() < 0.035 and hours > 0:
                hours *= rng.uniform(1.7, 2.5)
                spike = True
            energy = float(a["Rated_W"]) * hours / 1000.0
            # Daily energy budget: simulate a cutoff when the generated energy reaches
            # the configured limit. Energy is capped at the limit and end-of-day load
            # is shown as zero after the virtual relay opens.
            limit = max(float(a.get("Limit_kWh", 50.0)), 0.0)
            cutoff = bool(is_on and energy >= limit)
            if cutoff:
                energy = limit
                hours = min(hours, limit * 1000.0 / max(float(a["Rated_W"]), 1.0))
            watts = float(a["Rated_W"]) if is_on and hours > 0.02 and not cutoff else 0.0
            pf = float(a["Power_Factor"])
            current = watts / max(voltage * pf, 1) if watts else 0.0
            rows.append({
                "Date": pd.Timestamp(d), "Appliance": name, "Energy_kWh": energy,
                "Runtime_h": hours, "Power_W": watts, "Voltage_V": voltage,
                "Current_A": current, "Power_Factor": pf, "Spike_seeded": spike,
                "Virtual_Cutoff": cutoff
            })
    return pd.DataFrame(rows)

history = make_history(
    st.session_state.appliances, simulation_days, st.session_state.seed, noise,
    st.session_state.usage_factor, st.session_state.enabled, st.session_state.locked
)
today = pd.Timestamp(date.today())
today_data = history[history["Date"] == today]
total_today = today_data["Energy_kWh"].sum()
total_week = history[history["Date"] >= today - pd.Timedelta(days=6)]["Energy_kWh"].sum()
total_month = history[history["Date"] >= today - pd.Timedelta(days=29)]["Energy_kWh"].sum()
total_power = today_data["Power_W"].sum()
total_current = total_power / max(voltage * 0.92, 1)
bill = total_month * tariff_rate
bill_total = (bill + fixed_charge) * (1 + other_pct / 100)

# ---------- KPI cards ----------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Live simulated load", f"{total_power:,.0f} W", "Virtual junction")
k2.metric("Today's energy", f"{total_today:.2f} kWh")
k3.metric("Last 7 days", f"{total_week:.1f} kWh")
k4.metric("Last 30 days", f"{total_month:.1f} kWh")
k5.metric("Estimated bill", f"₹{bill_total:,.0f}", f"{state_name.split(' —')[0]} · estimate")

st.markdown("### 🔌 Virtual circuit topology")
topology = st.columns([1, 0.25, 1, 0.25, 1])
with topology[0]:
    st.info("**GRID INPUT**\n\n230 V simulated supply\n\nVirtual meter")
with topology[1]:
    st.markdown("<div style='text-align:center;padding-top:35px;color:#4be0c0;font-size:26px;'>⟶</div>", unsafe_allow_html=True)
with topology[2]:
    st.success("**SMART JUNCTION**\n\nPer-appliance channels\n\nPower + energy model")
with topology[3]:
    st.markdown("<div style='text-align:center;padding-top:35px;color:#4be0c0;font-size:26px;'>⟶</div>", unsafe_allow_html=True)
with topology[4]:
    st.warning("**APP / DASHBOARD**\n\nUsage limits\n\nSimulated cutoff + unlock")

tab_overview, tab_devices, tab_analytics, tab_bill, tab_method = st.tabs([
    "📊 Overview", "🎛️ Appliances & controls", "📈 Usage analytics", "🧾 Bill estimator", "🧠 Model & notes"
])

# ---------- Overview ----------
with tab_overview:
    left, right = st.columns([1.35, 1])
    with left:
        daily = history.groupby("Date", as_index=False)["Energy_kWh"].sum()
        fig = px.area(daily, x="Date", y="Energy_kWh", title="Daily household energy consumption",
                      color_discrete_sequence=["#37d9bf"])
        fig.update_traces(line_width=2, fillcolor="rgba(55,217,191,0.16)")
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=10,r=10,t=55,b=10), yaxis_title="Energy (kWh)", xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        by_app = history.groupby("Appliance", as_index=False)["Energy_kWh"].sum().sort_values("Energy_kWh", ascending=True)
        fig2 = px.bar(by_app, x="Energy_kWh", y="Appliance", orientation="h", title=f"Consumption by appliance · {simulation_days} days",
                       color="Energy_kWh", color_continuous_scale=["#1d5d75", "#38e0bd"])
        fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           coloraxis_showscale=False, margin=dict(l=10,r=10,t=55,b=10), xaxis_title="Energy (kWh)", yaxis_title="")
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("#### Meter readings (simulated)")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Voltage", f"{voltage} V")
    m2.metric("Current", f"{total_current:.2f} A")
    m3.metric("Active power", f"{total_power:.0f} W")
    m4.metric("Power factor", f"{(total_power / max(total_power, 1)) * 0.92:.2f}" if total_power else "0.00")
    st.caption("Power/current readings are a simplified model. Real appliances have changing loads, power factor, and startup currents.")

# ---------- Appliance controls ----------
with tab_devices:
    st.markdown("#### Manage each appliance channel")
    st.caption("Switches and cutoffs here change only the simulated data; they do not control physical devices.")
    for _, a in st.session_state.appliances.iterrows():
        name = a["Appliance"]
        c1, c2, c3, c4, c5 = st.columns([1.6, 1.0, 1.0, 1.2, 1.4])
        with c1:
            st.markdown(f"**{a['Icon']} {name}**")
            st.caption(f"Rated load: {a['Rated_W']:.0f} W")
        with c2:
            enabled_now = st.toggle("Channel ON", value=st.session_state.enabled.get(name, True), key=f"on_{name}")
            st.session_state.enabled[name] = enabled_now
        with c3:
            factor = st.number_input("Usage factor", 0.25, 2.5, float(st.session_state.usage_factor.get(name, 1.0)), 0.25, key=f"factor_{name}")
            st.session_state.usage_factor[name] = factor
        with c4:
            limit = st.number_input("Limit kWh/day", 0.1, 50.0, float(a["Limit_kWh"]), 0.1, key=f"limit_{name}")
            st.session_state.appliances.loc[st.session_state.appliances["Appliance"] == name, "Limit_kWh"] = limit
        with c5:
            if st.session_state.locked.get(name, False):
                st.error("SIMULATED CUTOFF")
                if st.button("Unlock in app", key=f"unlock_{name}"):
                    st.session_state.locked[name] = False
                    st.rerun()
            else:
                st.success("Channel available")
                if st.button("Lock channel", key=f"lock_{name}"):
                    st.session_state.locked[name] = True
                    st.rerun()
        st.divider()

    # The generated history applies the virtual cutoff at the configured daily budget.
    today_rows = history[history["Date"] == today]
    cutoffs = today_rows[today_rows["Virtual_Cutoff"]]
    if len(cutoffs):
        st.markdown("#### ⚠️ Simulated energy-limit cutoffs")
        for _, row in cutoffs.iterrows():
            st.warning(f"{row['Appliance']}: daily budget reached ({row['Energy_kWh']:.2f} kWh). The virtual relay is shown as opened for the remainder of the simulated day.")
    else:
        st.success("No configured daily energy limit triggered a virtual cutoff in today's generated readings.")

# ---------- Analytics ----------
with tab_analytics:
    granularity = st.radio("View interval", ["Daily", "Weekly", "Monthly"], horizontal=True)
    plot_data = history.copy()
    if granularity == "Daily":
        plot_data["Period"] = plot_data["Date"].dt.strftime("%d %b")
        title = "Daily appliance consumption"
    elif granularity == "Weekly":
        plot_data["Period"] = plot_data["Date"].dt.to_period("W").astype(str)
        title = "Weekly appliance consumption"
    else:
        plot_data["Period"] = plot_data["Date"].dt.to_period("M").astype(str)
        title = "Monthly appliance consumption"
    grouped = plot_data.groupby(["Period", "Appliance"], as_index=False)["Energy_kWh"].sum()
    fig3 = px.bar(grouped, x="Period", y="Energy_kWh", color="Appliance", barmode="stack", title=title)
    fig3.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       margin=dict(l=10,r=10,t=55,b=10), xaxis_title="", yaxis_title="Energy (kWh)")
    st.plotly_chart(fig3, use_container_width=True)

    st.markdown("#### 🔎 Sudden-hike detection")
    # Compare each appliance's most recent 7 days against its preceding 7 days.
    recent_start = today - pd.Timedelta(days=6)
    prior_start = today - pd.Timedelta(days=13)
    recent = history[(history["Date"] >= recent_start) & (history["Date"] <= today)].groupby("Appliance")["Energy_kWh"].sum()
    prior = history[(history["Date"] >= prior_start) & (history["Date"] < recent_start)].groupby("Appliance")["Energy_kWh"].sum()
    anomaly_rows = []
    for name in st.session_state.appliances["Appliance"]:
        r = float(recent.get(name, 0))
        p = float(prior.get(name, 0))
        change = ((r - p) / p * 100) if p > 0 else (100.0 if r > 0 else 0.0)
        anomaly_rows.append({"Appliance": name, "Previous 7 days (kWh)": round(p, 2),
                             "Latest 7 days (kWh)": round(r, 2), "Change (%)": round(change, 1),
                             "Flag": "Investigate" if change >= 25 else "Normal"})
    anomaly = pd.DataFrame(anomaly_rows).sort_values("Change (%)", ascending=False)
    st.dataframe(anomaly, use_container_width=True, hide_index=True)
    flags = anomaly[anomaly["Flag"] == "Investigate"]
    if len(flags):
        for _, r in flags.iterrows():
            st.warning(f"{r['Appliance']} increased by {r['Change (%)']:.1f}% versus the previous 7 days. Check runtime, settings, and appliance condition.")
    else:
        st.success("No appliance crossed the 25% week-on-week increase threshold.")
    st.caption("This is a simple baseline comparison, not a diagnosis. The generated history includes occasional demo spikes to show how alerts work.")

# ---------- Bill ----------
with tab_bill:
    st.markdown("#### Estimated monthly bill")
    b1, b2, b3 = st.columns(3)
    b1.metric("Monthly energy", f"{total_month:.2f} kWh")
    b2.metric("Energy charges", f"₹{bill:,.2f}")
    b3.metric("Estimated total", f"₹{bill_total:,.2f}")
    bill_breakdown = pd.DataFrame([
        {"Component": "Energy charge", "Calculation": f"{total_month:.2f} kWh × ₹{tariff_rate:.2f}/kWh", "Amount (₹)": round(bill, 2)},
        {"Component": "Monthly fixed charge", "Calculation": "User-entered tariff setting", "Amount (₹)": round(fixed_charge, 2)},
        {"Component": "Other charges", "Calculation": f"{other_pct:.1f}% of energy + fixed charges", "Amount (₹)": round((bill + fixed_charge) * other_pct / 100, 2)},
        {"Component": "Estimated total", "Calculation": "Sum of above", "Amount (₹)": round(bill_total, 2)},
    ])
    st.dataframe(bill_breakdown, use_container_width=True, hide_index=True)
    st.info("For a precise bill, configure the correct DISCOM, consumer category, consumption slabs, fixed charges, fuel adjustment, duty, taxes, subsidies, and billing-period rules. This demo uses one editable flat energy rate and is not an official bill.")
    st.markdown("**Tariff verification:** Rajasthan tariffs are published by the Rajasthan Electricity Regulatory Commission and individual DISCOMs. Use the latest tariff order for your exact provider and consumer category.")
    st.markdown("[RERC official tariff orders](https://rerc.rajasthan.gov.in/TariffOrders) · [Jaipur DISCOM official tariff page](https://energy.rajasthan.gov.in/jvvnl/pages/sm/department-page/138406/624)")

# ---------- Model / technical notes ----------
with tab_method:
    st.markdown("#### How the simulated system works")
    st.code("""
                 ┌───────────────────────────┐
  Grid input ───▶│ Virtual meter / main bus  │
                 └─────────────┬─────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
      Channel 1           Channel 2           Channel N
      AC / fan / etc.     Laptop / light      Other appliance
            │                  │                  │
      Power model        Power model        Power model
            └──────────────────┼──────────────────┘
                               ▼
                 Per-device kWh + timestamp
                               ▼
                 History → alerts → bill
                               ▼
                  App control (simulated)
""", language="text")
    st.markdown("#### Core formulas")
    st.latex(r"P = V \\times I \\times PF")
    st.latex(r"E\\;(\\mathrm{kWh}) = \\frac{P\\;(\\mathrm{W})\\times t\\;(\\mathrm{hours})}{1000}")
    st.latex(r"\\text{Energy charge} = \\text{units consumed}\\times\\text{rate per unit}")
    st.markdown("""
- **Meter model:** produces synthetic per-appliance readings, not physical sensor measurements.
- **Junction model:** each appliance is represented as an independent software channel.
- **Limit logic:** the simulation caps daily appliance energy at its configured budget and shows a virtual relay cutoff. The UI also supports manual simulated lock/unlock. Real-time cutoff needs a continuously updated measured energy counter and a safely designed control circuit.
- **Anomaly logic:** compares the latest seven days against the previous seven days and flags an increase of at least 25%.
- **Bill logic:** estimates cost using a configurable flat rate. Real tariff rules are often slab-based and vary by DISCOM, category, billing cycle, and subsidies.
""")
    st.warning("Safety note: do not connect a student prototype directly to household mains. Any real circuit, current sensor, enclosure, isolation, fuse/breaker, contactor/relay, and fail-safe cutoff design must be reviewed and installed by a qualified electrical professional.")

# ---------- Export readings ----------
st.markdown("---")
st.markdown("### 📥 Export generated meter readings")
csv = history.drop(columns=["Spike_seeded"]).to_csv(index=False).encode("utf-8")
st.download_button("Download simulated readings (CSV)", data=csv,
                   file_name="smartgrid_simulated_meter_readings.csv", mime="text/csv")
st.caption("SMARTGRID prototype · Synthetic data only · No physical meter or appliance is connected.")
