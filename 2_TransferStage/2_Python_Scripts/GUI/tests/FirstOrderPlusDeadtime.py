import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
import pandas as pd

# Step response data (time, output)
# Replace this with actual step-response data
time = np.linspace(0, 20, 100)  # time vector
K = 2.0    # process gain
tau = 5.0  # time constant
L = 2.0    # dead time
u_step = 1.0  # step input

# Simulated FOPDT system response (first-order system with dead time)
def fopdt_model(t, K, tau, L):
    return K * u_step * (1 - np.exp(-(t - L) / tau)) * (t > L)

# Generate data
response = fopdt_model(time, K, tau, L) + 0.05 * np.random.normal(size=len(time))  # add noise
df = pd.read_json(r"C:\Users\Operator\TransferStage\5_Raw_Data\OpenLoop.json")
response = df["Flow"]
time = df["Time"]
print(response)
print(df)

# Fit the FOPDT model to the data
def fopdt_fit(t, K, tau, L):
    return K * (1 - np.exp(-(t - L) / tau)) * (t > L)

# Use curve_fit to estimate K, tau, and L
popt, _ = curve_fit(fopdt_fit, time, response, bounds=([0, 0, 0], [np.inf, np.inf, np.inf]))

# Extract the identified parameters
K_fit, tau_fit, L_fit = popt
print(f"Estimated K: {K_fit}, tau: {tau_fit}, L: {L_fit}")

# Plot the original response and the fitted response
plt.plot(time, response, label="Original Response")
plt.plot(time, fopdt_fit(time, *popt), '--', label="FOPDT Fitted")
#plt.plot(time,df["Pressure"])
plt.xlabel("Time")
plt.ylabel("Response")
plt.legend()
plt.show()


def ziegler_nichols_fopdt(K, tau, L):
    # Ziegler-Nichols Tuning for PID
    Kp = (1.2 * tau) / (K * L)
    Ti = 2 * L
    Td = 0.5 * L
    return Kp, Ti, Td

# Get the PID parameters
Kp, Ti, Td = ziegler_nichols_fopdt(K_fit, tau_fit, L_fit)
print(f"Ziegler-Nichols Tuning: Kp = {Kp}, Ti = {Ti}, Td = {Td}")

from scipy.integrate import odeint
from scipy.optimize import minimize

# Simulate a first-order process with dead time and PID controller
def process_sim(y, t, Kp, Ti, Td, K, tau, L, setpoint, u):
    e = setpoint - y[0]  # Error: setpoint - current output
    delta_t = max(t - y[2], 1e-6)  # Avoid division by zero

    if t > L and delta_t > 1e-6:
        integral = y[1] + e * delta_t  # Accumulate error with delta_t
        integral = np.clip(integral, -1e5, 1e5)  # Anti-windup: limit integral term
        derivative = (e - y[3]) / delta_t  # Derivative term

        # Calculate the PID control signal
        control_signal = Kp * e + (Kp / Ti) * integral + Kp * Td * derivative

        # Limit control signal to prevent overflow (e.g., saturation limit)
        control_signal = np.clip(control_signal, -1e3, 1e3)
    else:
        integral = y[1]
        control_signal = 0.0  # No control signal before dead time

    # Process dynamics (first-order plus dead time)
    dydt = (K * control_signal - y[0]) / tau  # Process model: dy/dt = (K * u - y) / tau
    return [dydt, integral, t, e]



# Objective function (e.g., IAE)
def objective(params, time, setpoint, K, tau, L):
    Kp, Ti, Td = params
    y0 = [0, 0, 0, 0]  # initial conditions: [process output, integral, time, error]
    sol = odeint(process_sim, y0, time, args=(Kp, Ti, Td, K, tau, L, setpoint, 0), rtol=1e-5, atol=1e-7)


    # Calculate the error and return the IAE
    error = setpoint - sol[:, 0]
    iae = np.trapz(np.abs(error), time)
    return iae

# Initial guess for the PID parameters
initial_guess = [Kp, Ti, Td]

# Optimize the PID parameters
res = minimize(objective, initial_guess, args=(time, u_step, K_fit, tau_fit, L_fit), bounds=[(0, None), (0, None), (0, None)])

# Optimized parameters
Kp_opt, Ti_opt, Td_opt = res.x
print(f"Optimized PID: Kp = {Kp_opt}, Ti = {Ti_opt}, Td = {Td_opt}")
"""
"""