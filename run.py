import streamlit as st
import fastf1
import fastf1.plotting
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# --- CONFIGURATION ---
st.set_page_config(page_title="F1 Analytics Hub", layout="wide", page_icon="🏎️")
fastf1.plotting.setup_mpl(misc_mpl_mods=False)

# Enable Cache
if not os.path.exists('cache'):
    os.makedirs('cache')
fastf1.Cache.enable_cache('cache')


# --- HELPER FUNCTIONS ---

@st.cache_data
def get_race_schedule(year):
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        return schedule[schedule['EventDate'] < pd.Timestamp.now() + pd.Timedelta(days=7)]
    except:
        return pd.DataFrame()


@st.cache_data
def get_driver_list(year, gp, session):
    try:
        session = fastf1.get_session(year, gp, session)
        session.load(telemetry=False, weather=False, messages=False)
        return sorted(session.results['Abbreviation'].unique().tolist())
    except:
        return []


def format_time(td):
    """Converts Timedelta to '1:23.456' format"""
    if pd.isna(td): return ""
    total_seconds = td.total_seconds()
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:06.3f}"


# --- SIDEBAR ---
st.sidebar.title("🏎️ F1 Hub")
year = st.sidebar.selectbox("Year", [2025, 2024, 2023], index=1)
schedule = get_race_schedule(year)
gp = st.sidebar.selectbox("Grand Prix", schedule['EventName'].tolist())
session_type = st.sidebar.selectbox("Session", ["R", "Q", "S", "FP1", "FP2", "FP3"], index=0)

st.sidebar.markdown("---")
# We load the driver list for the dropdowns
drivers = get_driver_list(year, gp, session_type)

if drivers:
    d1 = st.sidebar.selectbox("Driver 1", drivers, index=0)
    d2 = st.sidebar.selectbox("Driver 2", drivers, index=min(1, len(drivers) - 1))
    load_btn = st.sidebar.button("Load Dashboard")
else:
    st.sidebar.warning("Select a race to load drivers.")
    load_btn = False

# --- MAIN DASHBOARD ---
if load_btn:
    st.title(f"{year} {gp} - {session_type}")

    with st.spinner("Loading Session Data..."):
        try:
            session = fastf1.get_session(year, gp, session_type)
            session.load(telemetry=True, weather=False)
            laps = session.laps
        except Exception as e:
            st.error(f"Error loading data: {e}")
            st.stop()

    # Create Tabs
    tab1, tab2, tab3 = st.tabs(["⚡ Telemetry Comparison", "⏱️ Lap-by-Lap", "🏆 Leaderboard"])

    # --- TAB 1: TELEMETRY (Your existing feature) ---
    with tab1:
        st.subheader(f"Telemetry: {d1} vs {d2}")
        try:
            l1 = laps.pick_driver(d1).pick_fastest()
            l2 = laps.pick_driver(d2).pick_fastest()

            if l1 is None or l2 is None:
                st.warning("One of the drivers didn't set a time.")
            else:
                t1 = l1.get_car_data().add_distance()
                t2 = l2.get_car_data().add_distance()

                # Speed Trace
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=t1['Distance'], y=t1['Speed'], name=d1, line=dict(color='cyan')))
                fig.add_trace(go.Scatter(x=t2['Distance'], y=t2['Speed'], name=d2, line=dict(color='orange')))
                fig.update_layout(title="Speed Comparison (Fastest Lap)", xaxis_title="Distance (m)",
                                  yaxis_title="Speed (km/h)", template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)

                # Delta Info
                delta = (l2['LapTime'] - l1['LapTime']).total_seconds()
                color = "green" if delta > 0 else "red"
                st.markdown(f"**Gap:** {d1} was **{abs(delta):.3f}s** {'faster' if delta > 0 else 'slower'} than {d2}")

        except Exception as e:
            st.error(f"Telemetry Error: {e}")

    # --- TAB 2: LAP BY LAP ANALYSIS ---
    with tab2:
        st.subheader("Race Pace Analysis")

        # 1. Select Drivers to Compare (Default to the 2 from sidebar)
        selected_drivers = st.multiselect("Select Drivers to Compare", drivers, default=[d1, d2])

        if selected_drivers:
            # Filter laps for selected drivers
            driver_laps = laps[laps['Driver'].isin(selected_drivers)].copy()

            # Remove "In Laps" and "Out Laps" (abnormally slow) and None times
            driver_laps = driver_laps.pick_quicklaps()
            driver_laps.dropna(subset=['LapTime'], inplace=True)

            # Convert LapTime to Seconds for plotting
            driver_laps['LapTimeSec'] = driver_laps['LapTime'].dt.total_seconds()

            # Line Chart
            fig_laps = px.line(
                driver_laps,
                x="LapNumber",
                y="LapTimeSec",
                color="Driver",
                markers=True,
                title="Lap Time Evolution",
                color_discrete_sequence=px.colors.qualitative.Bold
            )
            # Customizing Tooltip to show formatted time
            fig_laps.update_traces(
                hovertemplate="<b>Lap %{x}</b><br>Time: %{y:.3f}s"
            )
            fig_laps.update_layout(yaxis_title="Lap Time (s)", xaxis_title="Lap Number", template="plotly_dark")
            st.plotly_chart(fig_laps, use_container_width=True)

            # Lap Data Table
            with st.expander("View Raw Lap Data"):
                display_cols = ['Driver', 'LapNumber', 'LapTime', 'Sector1Time', 'Sector2Time', 'Sector3Time',
                                'Compound']
                # Format the display dataframe
                display_df = driver_laps[display_cols].copy()
                display_df['LapTime'] = display_df['LapTime'].apply(format_time)
                display_df['Sector1Time'] = display_df['Sector1Time'].apply(format_time)
                display_df['Sector2Time'] = display_df['Sector2Time'].apply(format_time)
                display_df['Sector3Time'] = display_df['Sector3Time'].apply(format_time)
                st.dataframe(display_df, use_container_width=True)

    # --- TAB 3: LEADERBOARD GRID ---
    with tab3:
        st.subheader("🏆 Fastest Lap Grid")

        # 1. Group by driver to find best lap
        # We use pick_quicklaps to filter out pit in/out laps
        fastest_laps = laps.pick_quicklaps().groupby("Driver")["LapTime"].min().reset_index()

        if not fastest_laps.empty:
            # Sort by time
            fastest_laps = fastest_laps.sort_values("LapTime")

            # Calculate Gap to Pole
            pole_time = fastest_laps.iloc[0]["LapTime"]
            fastest_laps["Gap"] = fastest_laps["LapTime"] - pole_time

            # Format Columns
            fastest_laps["Time"] = fastest_laps["LapTime"].apply(format_time)
            fastest_laps["Gap"] = fastest_laps["Gap"].apply(
                lambda x: f"+{x.total_seconds():.3f}s" if x.total_seconds() > 0 else "-")

            # Add Position
            fastest_laps.insert(0, 'Pos', range(1, 1 + len(fastest_laps)))

            # Add Tyre Compound info if available
            # We merge back with original laps to find the compound used for that specific fast lap
            fastest_laps_detailed = pd.merge(
                fastest_laps,
                laps[['Driver', 'LapTime', 'Compound']],
                on=['Driver', 'LapTime'],
                how='left'
            )

            # Clean up display
            final_grid = fastest_laps_detailed[['Pos', 'Driver', 'Time', 'Gap', 'Compound']]

            # Styling the dataframe
            st.dataframe(
                final_grid,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Pos": st.column_config.NumberColumn("Pos", format="%d"),
                    "Compound": st.column_config.TextColumn("Tyre"),
                }
            )
        else:
            st.info("No lap times available yet.")

elif not load_btn:
    st.info("👈 Select a race from the sidebar to begin.")