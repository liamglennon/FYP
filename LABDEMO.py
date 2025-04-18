"""
Aligned 4‑quadrant RF‑test dashboard
------------------------------------
Adds a “SIMULATE (no‑COM)” option that completely bypasses the serial
connection so the app can run stand‑alone.
"""

import os, atexit, serial, serial.tools.list_ports
import dash
from dash import dcc, html, callback_context
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import base64
import io

# ───── configuration ───────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(__file__)
CSV_PATH  = (os.path.join(BASE_DIR, "Molex.csv")
             if os.path.exists(os.path.join(BASE_DIR, "Molex.csv"))
             else r"C:\Users\LIAMG\Desktop\FYP DATA\Rad Patterns\Molex.csv")

df              = pd.read_csv(CSV_PATH, names=["Angle", "Signal"], skiprows=1)
angles, signals = df["Angle"].tolist(), df["Signal"].tolist()
pattern_power   = signals[0]

# serial / simulation runtime flags
ser            = None          # serial.Serial instance or None
simulation     = True          # start in SIM mode until user connects

def list_ports() -> list[str]:
    """Return all COM ports plus the SIM option."""
    ports = sorted(p.device for p in serial.tools.list_ports.comports())
    return ["SIMULATE (no‑COM)"] + ports

def open_port(port: str):
    """Open or close the physical serial port."""
    global ser, simulation
    # switch to simulation if the user picked the special option
    if port == "SIMULATE (no‑COM)":
        if ser and ser.is_open:
            ser.close()
        ser = None
        simulation = True
        return

    # physical port
    simulation = False
    if ser and ser.is_open:
        ser.close()
    ser = serial.Serial(port, 115200, timeout=0.2)
    atexit.register(lambda: ser.close() if ser and ser.is_open else None)

def safe_write(cmd: bytes):
    """Send bytes only when a real port is open."""
    if not simulation and ser and ser.is_open:
        ser.write(cmd)
        ser.flush()

# ───── numeric constants ────────────────────────────────────────────────
SPAN_HZ = 50e6  # 0.05 GHz span
PTS       = 1001
SIG_W     = 500e3
DEFAULT_CF_HZ = 5.9e9          # initial centre freq

FREQS_GHZ = np.linspace(DEFAULT_CF_HZ - SPAN_HZ / 2,
                        DEFAULT_CF_HZ + SPAN_HZ / 2,
                        PTS) / 1e9

idx, x_data, y_data = 0, [], []

# ───── reusable style snippets ─────────────────────────────────────────────
BEZEL = {
    "backgroundColor": "#dce3ea",
    "border": "1px solid #8d99a6",
    "borderRadius": "8px",
    "boxShadow": "inset 0 0 4px rgba(0,0,0,.35)",
    "display": "flex",
    "flexDirection": "column",
    "padding": "12px",
    "height": "100%",
    "boxSizing": "border-box",
}

TITLE_BAR = {
    "backgroundColor": "#2b2d30",
    "color": "#e2e6ea",
    "fontSize": "0.85em",
    "letterSpacing": "0.08em",
    "padding": "4px 10px",
    "borderRadius": "4px",
    "userSelect": "none",
    "marginBottom": "10px",
}

app = dash.Dash(__name__)
app.title = "RF Lab Dashboard"

# ───── layout grid ─────────────────────────────────────────────────────────
app.layout = html.Div(
    style={
        "height": "100vh",
        "display": "grid",
        "gridTemplateColumns": "1fr 1fr",
        "gridTemplateRows": "1fr 1fr",
        "gap": "10px",
        "padding": "10px",
        "backgroundColor": "#2e323c",
        "boxSizing": "border-box",
    },
    children=[
        # ─────────────────────────────── top‑left (FSW Panel) ──────────────────────
        html.Div(
            style=BEZEL,
            children=[
                html.Div("R&S  FSW ▸ SIGNAL & SPECTRUM ANALYZER", style=TITLE_BAR),
                html.Div(
                    "Ref 0 dBm  RBW 500 kHz  VBW 500 kHz  Auto Sweep",
                    style={"fontFamily": "monospace", "fontSize": "0.75em",
                           "color": "#003399", "marginBottom": "4px"},
                ),
                dcc.Graph(id="spectrum-graph", config={"displayModeBar": False},
                          style={"flex": "1 1 0"}),
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between", "marginTop": "6px"},
                    children=[
                        html.Div("CF 5.9 GHz  1001 pts  Span 50 MHz  Measuring…",
                                 style={"fontFamily": "monospace", "fontSize": "0.75em",
                                        "color": "#003399"}),
                        html.Button("Auto", id="auto-btn", n_clicks=0,
                                    style={
                                        "backgroundColor": "#007bff",
                                        "color": "white",
                                        "border": "none",
                                        "borderRadius": "4px",
                                        "padding": "4px 10px",
                                        "fontSize": "0.8em",
                                        "cursor": "pointer",
                                    }),
                    ],
                ),
                dcc.Interval(id="interval-sweep", interval=100, n_intervals=0),
            ],
        ),
        # ─────────────────────────────── top‑right
        html.Div(
            style=BEZEL | {"fontFamily": "monospace", "color": "#000"},
            children=[
                html.Div("R&S  SMW200A ▸ VECTOR SIGNAL GENERATOR", style=TITLE_BAR),
                html.Div(
                    ["Frequency ",
                     html.Span(id="vsg-frequency", children="5.900 000 000 000",
                               style={"fontSize": "2.4em", "fontFamily": "Courier",
                                      "color": "#003399", "letterSpacing": "0.06em"}),
                     " GHz"],
                    style={"fontSize": "0.9em", "fontWeight": "600", "marginBottom": "8px"},
                ),
                html.Div(
                    style={
                        "display": "flex",
                        "gap": "10px",
                        "justifyContent": "center",
                        "marginBottom": "14px",
                    },
                    children=[
                        html.Button("▲", id="freq-up-btn", n_clicks=0,
                                    style={
                                        "width": "44px", "height": "34px",
                                        "fontSize": "1.3em", "fontWeight": "700",
                                        "backgroundColor": "#007bff",   # bright blue
                                        "color": "white",
                                        "border": "none",
                                        "borderRadius": "4px",
                                        "cursor": "pointer",
                                    }),
                        html.Button("▼", id="freq-down-btn", n_clicks=0,
                                    style={
                                        "width": "44px", "height": "34px",
                                        "fontSize": "1.3em", "fontWeight": "700",
                                        "backgroundColor": "#007bff",
                                        "color": "white",
                                        "border": "none",
                                        "borderRadius": "4px",
                                        "cursor": "pointer",
                                    }),
                    ],
                ),
                html.Div(
                    [html.Div(t, style={"backgroundColor": c, "padding": "4px 10px",
                                        "borderRadius": "4px", "color": "#fff",
                                        "fontSize": "0.8em", "fontWeight": "600"})
                     for t, c in [("RF On", "#0097e6"), ("Remote", "#6c7a89"),
                                  ("Int Ref", "#6c7a89"), ("Mod Off", "#6c7a89")]],
                    style={"display": "flex", "gap": "6px", "marginBottom": "14px"},
                ),
            ],
        ),
        # ─────────────────────────────── bottom‑left
        html.Div(
            style=BEZEL,
            children=[
                dcc.Graph(id="pattern-graph", config={"displayModeBar": False},
                          style={"flex": "1 1 0"}),
                dcc.Interval(id="interval-pattern", interval=100, n_intervals=0),
            ],
        ),
        # ─────────────────────────────── bottom‑right
        html.Div(
            style=BEZEL | {"flexDirection": "row", "gap": "18px"},
            children=[
                # LCD
                html.Div(
                    id="lcd",
                    children=[
                        html.Div("Device           Pos.   Pol.  Angle"),
                        html.Div("MCU", style={"opacity": ".8"}),
                        html.Div(id="lcd-angle", children="Turn Table       0.00°"),
                        html.Div("=>Antenna Mast   not referenced"),
                        html.Br(),
                        html.Div("new value                reference"),
                    ],
                    style={"flex": "1 1 0",
                           "background": "linear-gradient(180deg,#6ac0ff 0%,#4aa6f0 100%)",
                           "border": "2px solid #0e4d8b", "borderRadius": "4px",
                           "boxShadow": "inset 0 0 12px rgba(0,0,0,.5)",
                           "fontFamily": "Courier New, monospace", "color": "white",
                           "fontSize": ".85em", "lineHeight": "1.35em", "padding": "10px"},
                ),
                # keypad / controls
                html.Div(
                    style={"display": "flex", "flexDirection": "column",
                           "gap": "18px", "alignItems": "center"},
                    children=[
                        # arrow D‑pad
                        html.Div(
                            style={"display": "grid",
                                   "gridTemplateColumns": "repeat(3, 40px)",
                                   "gridTemplateRows": "repeat(3, 40px)", "gap": "6px"},
                            children=[
                                html.Div(), html.Button("▲", style={"width": 40, "height": 40}), html.Div(),
                                html.Button("◀", style={"width": 40, "height": 40}),
                                html.Button("⟳", id="start-btn", n_clicks=0,
                                            style={"width": 40, "height": 40,
                                                   "backgroundColor": "#28a745", "color": "white"}),
                                html.Button("▶", style={"width": 40, "height": 40}),
                                html.Div(), html.Button("▼", style={"width": 40, "height": 40}), html.Div(),
                            ],
                        ),
                        # motor control row
                        html.Div(
                            style={"display": "flex", "gap": "8px"},
                            children=[
                                html.Button("CW", id="cw-btn",
                                            style={"backgroundColor": "#007bff", "color": "white",
                                                   "width": 50, "height": 36, "fontWeight": "bold"}),
                                html.Button("CCW", id="ccw-btn",
                                            style={"backgroundColor": "#007bff", "color": "white",
                                                   "width": 50, "height": 36, "fontWeight": "bold"}),
                                html.Button("⏹", id="mot-stop-btn",
                                            style={"backgroundColor": "#dc3545", "color": "white",
                                                   "width": 50, "height": 36, "fontWeight": "bold"}),
                            ],
                        ),
                        # serial port selector
                        html.Div(
                            style={"display": "flex", "alignItems": "center", "gap": "6px"},
                            children=[
                                html.Label("Serial:", style={"fontSize": ".8em"}),
                                dcc.Dropdown(
                                    id="port-select",
                                    options=[{"label": p, "value": p} for p in list_ports()],
                                    value="SIMULATE (no‑COM)",
                                    clearable=False,
                                    style={"width": "160px", "fontSize": "0.85em"},
                                ),
                                html.Button("Connect", id="connect-btn", n_clicks=0,
                                            style={"height": "32px"}),
                                html.Span("Simulation", id="serial-status",
                                          style={"fontSize": ".8em"}),
                            ],
                        ),
                        # numeric keypad
                        html.Div(
                            style={"display": "grid", "gridTemplateColumns": "repeat(3, 40px)",
                                   "gridAutoRows": "40px", "gap": "6px"},
                            children=[
                                *[html.Button(str(n), style={"width": 40, "height": 40})
                                  for n in range(7, 10)],
                                *[html.Button(str(n), style={"width": 40, "height": 40})
                                  for n in range(4, 7)],
                                *[html.Button(str(n), style={"width": 40, "height": 40})
                                  for n in range(1, 4)],
                                html.Button("0", style={"gridColumn": "1 / span 2", "height": 40}),
                                html.Button(".", style={"width": 40, "height": 40}),
                            ],
                        ),
                        # soft buttons
                        html.Div(
                            style={"display": "flex", "flexDirection": "column", "gap": "6px"},
                            children=[
                                html.Button("STOP", id="stop-btn", n_clicks=0,
                                            style={"backgroundColor": "#dc3545", "color": "white",
                                                   "width": 120, "height": 32}),
                                html.Button("Reset", id="reset-btn", n_clicks=0,
                                            style={
                                                "backgroundColor": "#dc3545",  # Red button
                                                "color": "white",
                                                "border": "none",
                                                "borderRadius": "4px",
                                                "padding": "6px 12px",
                                                "fontSize": "0.9em",
                                                "cursor": "pointer",
                                                "marginTop": "10px",
                                            }),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        # File upload component
        html.Div(
            style={"gridColumn": "1 / span 2", "textAlign": "center", "marginBottom": "10px"},
            children=[
                html.Label("Upload a CSV File:", style={"color": "white", "fontSize": "1em"}),
                dcc.Upload(
                    id="upload-data",
                    children=html.Button("Upload File", style={"fontSize": "1em"}),
                    style={"marginTop": "10px"},
                    multiple=False,
                ),
                html.Div(id="upload-status", style={"color": "white", "marginTop": "10px"}),
            ],
        ),
        dcc.Store(id="scan-state", data={"active": False}),
        dcc.Store(id="frequency-state", data={"frequency": 5.9}),   # VSG (GHz)
        dcc.Store(id="spectrum-axis",   data={"center_hz": DEFAULT_CF_HZ}),
        # Add a hidden div to the layout
        html.Div(id="serial-feedback", style={"display": "none"}),
    ],
)

# ───── callbacks ───────────────────────────────────────────────────────────
@app.callback(
    Output("serial-status", "children"),
    Input("connect-btn", "n_clicks"),
    State("port-select", "value"),
    prevent_initial_call=True,
)
def connect_serial(_, port):
    try:
        open_port(port)
        return "Simulation" if simulation else f"Connected {port}"
    except serial.SerialException as e:
        return f"Error {e}"

@app.callback(
    Output("serial-feedback", "children"),  # Write to the hidden div
    [Input("cw-btn", "n_clicks"),
     Input("ccw-btn", "n_clicks"),
     Input("mot-stop-btn", "n_clicks")],
    prevent_initial_call=True,
)
def motor_control(n_cw, n_ccw, n_stop):
    trig = callback_context.triggered[0]["prop_id"].split(".")[0]
    cmd = {"cw-btn": b":CW\n", "ccw-btn": b":CCW\n", "mot-stop-btn": b":STOP\n"}.get(trig)
    safe_write(cmd) if cmd else None
    return ""  # Dummy content

@app.callback(
    Output("spectrum-graph", "figure"),
    [
        Input("interval-sweep", "n_intervals"),
        Input("auto-btn", "n_clicks")
    ],
    [
        State("frequency-state", "data"),
        State("spectrum-axis", "data")
    ],
)
def update_spectrum(n_intervals, n_auto, freq_state, axis_state):
    # Decide center_hz only when Auto was clicked
    CF_HZ = freq_state["frequency"] * 1e9
    center_hz = axis_state["center_hz"]

    if callback_context.triggered[0]["prop_id"] == "auto-btn.n_clicks":
        center_hz = CF_HZ

    freqs_hz = np.linspace(center_hz - SPAN_HZ / 2, center_hz + SPAN_HZ / 2, PTS)
    freqs_ghz = freqs_hz / 1e9

    noise = np.clip(-90 + np.random.normal(0, 5.5, PTS), -np.inf, -80)
    amp = pattern_power + 100
    sig = -100 + amp * np.exp(-((freqs_hz - CF_HZ + 150e3) ** 2) / (2 * SIG_W ** 2))
    y = np.maximum(noise, sig)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=freqs_ghz, y=y, mode="lines", line=dict(color="yellow", width=1)))
    fig.add_vline(x=CF_HZ / 1e9, line=dict(color="#00bfff", dash="dash"))
    fig.update_layout(
        xaxis=dict(
            title="Frequency (GHz)",
            range=[(center_hz - SPAN_HZ / 2) / 1e9, (center_hz + SPAN_HZ / 2) / 1e9],
            gridcolor="#617192",
            color="white",
        ),
        yaxis=dict(title="Power (dBm)", range=[-100, 0], gridcolor="#617192", color="white"),
        paper_bgcolor="#1b202c",
        plot_bgcolor="#1b202c",
        margin=dict(l=40, r=30, t=10, b=40),
        font=dict(family="Consolas", size=13, color="white"),
    )
    return fig

@app.callback(Output("scan-state", "data"),
              [Input("start-btn", "n_clicks"), Input("stop-btn", "n_clicks")],
              State("scan-state", "data"))
def toggle_scan(_start, _stop, state):
    if not callback_context.triggered:
        return state
    state["active"] = callback_context.triggered[0]["prop_id"].startswith("start-btn")
    return state

@app.callback(
    [Output("pattern-graph", "figure"),
     Output("lcd-angle", "children")],
    [Input("interval-pattern", "n_intervals"),
     Input("reset-btn", "n_clicks")],
    [State("scan-state", "data")],
)
def pattern(n_intervals, reset_clicks, state):
    global idx, pattern_power, x_data, y_data

    if callback_context.triggered[0]["prop_id"] == "reset-btn.n_clicks":
        idx = 0
        x_data.clear()
        y_data.clear()
        state["active"] = False

    if state.get("active") and idx < len(angles) and angles[idx] <= 360:
        safe_write(b"STEP\n")
        x_data.append(angles[idx])
        y_data.append(signals[idx])
        pattern_power = signals[idx]
        idx += 1
    elif idx >= len(angles) or (angles[idx] > 360 if idx < len(angles) else False):
        state["active"] = False

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_data, y=y_data, mode="markers",
                             marker=dict(size=6, color="#00f700", symbol="cross")))
    fig.update_layout(
        xaxis=dict(
            title="Azimuth (°)",
            range=[0, 360],
            tick0=0,
            dtick=20,
            gridcolor="lightgrey",
            color="black",  # Axis labels in black
            zeroline=False,
        ),
        yaxis=dict(
            title="RF level (dBm)",
            range=[-100, 0],
            tick0=-100,
            dtick=10,
            gridcolor="lightgrey",
            color="black",  # Axis labels in black
            zeroline=False,
        ),
        paper_bgcolor="#dce3ea",  # Match the border color
        plot_bgcolor="#000000",  # Set the actual plot background to black
        margin=dict(l=50, r=40, t=30, b=40),
        font=dict(family="Courier New, monospace", color="black", size=14),  # Text in black
    )
    angle = f"Turn Table       {x_data[-1]:0.2f}°" if x_data else "Turn Table       0.00°"
    return fig, angle

@app.callback(
    Output("upload-status", "children"),
    Input("upload-data", "contents"),
    State("upload-data", "filename"),
    prevent_initial_call=True,
)
def update_csv(contents, filename):
    global df, angles, signals, pattern_power
    if contents is None:
        return "No file uploaded."

    try:
        # Decode the uploaded file
        content_type, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)
        uploaded_df = pd.read_csv(io.StringIO(decoded.decode("utf-8")), names=["Angle", "Signal"], skiprows=1)

        # Update global variables
        df = uploaded_df
        angles, signals = df["Angle"].tolist(), df["Signal"].tolist()
        pattern_power = signals[0]

        return f"File '{filename}' uploaded successfully."
    except Exception as e:
        return f"Error processing file: {e}"

@app.callback(
    [Output("vsg-frequency", "children"), Output("frequency-state", "data")],
    [Input("freq-up-btn", "n_clicks"), Input("freq-down-btn", "n_clicks")],
    State("frequency-state", "data"),
    prevent_initial_call=True,
)
def update_frequency(n_up, n_down, freq_state):
    # Determine which button was clicked
    triggered_id = callback_context.triggered[0]["prop_id"].split(".")[0]
    frequency = freq_state["frequency"]

    # Update frequency based on button click
    if triggered_id == "freq-up-btn":
        frequency += 0.01  # Increment by 10 MHz
    elif triggered_id == "freq-down-btn":
        frequency -= 0.01  # Decrement by 10 MHz

    # Ensure frequency stays within a valid range (e.g., 5.8 GHz to 6.0 GHz)
    frequency = max(5.8, min(6.0, frequency))

    # Format frequency for display
    formatted_frequency = f"{frequency:.3f} 000 000 000"

    # Update the frequency state
    return formatted_frequency, {"frequency": frequency}

@app.callback(
    Output("spectrum-axis", "data"),
    Input("auto-btn", "n_clicks"),
    State("frequency-state", "data"),
    prevent_initial_call=True,
)
def recenter_axis(_, freq_state):
    return {"center_hz": freq_state["frequency"] * 1e9}

# ───── run ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=8050)
