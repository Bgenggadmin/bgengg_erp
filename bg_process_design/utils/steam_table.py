"""
Steam Table - Saturated Steam Properties
Source: Extracted from B&G Engineering ECOX-BG design sheets
Columns: Temp(C), Press(BAR), Volume(m3/kg), Density(kg/m3), LtHeat(kJ/kg), LtHeat(kcal/kg), HV(kcal/kg)
"""
import bisect


# Sparse reference data (full table baked into interpolator)
# (temp_C, press_BAR, density_kg_m3, lt_heat_kcal_kg, hv_kcal_kg)
STEAM_TABLE = [
    (0,    0.00611,  0.00485,  597.61, 597.61),
    (10,   0.01227,  0.00940,  591.95, 601.95),
    (20,   0.02337,  0.01729,  586.31, 606.31),
    (25,   0.03168,  0.02304,  583.49, 608.49),
    (30,   0.04244,  0.03037,  580.67, 610.67),
    (40,   0.07374,  0.05115,  574.99, 614.99),
    (50,   0.12333,  0.08299,  569.28, 619.28),
    (55,   0.15746,  0.10440,  566.39, 621.39),
    (60,   0.19919,  0.13023,  563.47, 623.47),
    (65,   0.25013,  0.16124,  560.54, 625.54),
    (70,   0.31172,  0.19818,  557.57, 627.57),
    (75,   0.38559,  0.24190,  554.59, 629.59),
    (80,   0.47372,  0.29334,  551.55, 631.55),
    (85,   0.57825,  0.35348,  548.52, 633.52),
    (90,   0.70118,  0.42355,  545.41, 635.41),
    (95,   0.84531,  0.50454,  542.31, 637.31),
    (100,  1.00000,  0.59032,  539.39, 639.39),
    (105,  1.20010,  0.70028,  536.07, 641.07),
    (110,  1.46662,  0.83507,  532.49, 642.49),
    (115,  1.69994,  0.96993,  529.31, 644.31),
    (120,  1.99993,  1.12956,  525.94, 645.94),
    (125,  2.33326,  1.28750,  522.91, 647.91),
    (130,  2.70000,  1.49611,  519.28, 649.28),
    (133,  2.99990,  1.65125,  516.79, 649.79),
    (135,  3.13323,  1.70940,  515.77, 650.77),
    (140,  3.59988,  1.95925,  512.28, 652.28),
    (145,  4.19986,  2.26449,  508.27, 653.27),
    (150,  4.79984,  2.56805,  504.61, 654.61),
    (155,  5.39982,  2.91971,  500.72, 655.72),
    (160,  6.13313,  3.24851,  497.13, 657.13),
    (165,  6.99977,  3.66703,  493.31, 658.31),
    (170,  7.99974,  4.16146,  488.89, 658.89),
    (175,  8.99970,  4.65549,  484.83, 659.83),
    (180,  9.99967,  5.14668,  481.01, 661.01),
    (185,  11.33296, 5.75209,  476.83, 661.83),
    (190,  12.53292, 6.36335,  472.29, 662.29),
    (195,  13.99954, 7.10732,  467.65, 662.65),
    (200,  15.66615, 7.91557,  462.73, 662.73),
    (210,  18.99938, 9.56023,  453.70, 663.70),
    (220,  22.99924, 11.52605, 443.91, 663.91),
    (230,  27.99908, 14.00756, 432.78, 662.78),
    (250,  39.99868, 20.10050, 409.25, 659.25),
]


def _interp(x, table, xi, yi):
    """Linear interpolate y at x from table (sorted by xi)."""
    xs = [r[xi] for r in table]
    if x <= xs[0]:
        return table[0][yi]
    if x >= xs[-1]:
        return table[-1][yi]
    i = bisect.bisect_left(xs, x)
    x0, x1 = xs[i - 1], xs[i]
    y0, y1 = table[i - 1][yi], table[i][yi]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def pressure_at_temp(temp_c: float) -> float:
    """Saturation pressure (bar-a) at temperature °C."""
    return _interp(temp_c, STEAM_TABLE, 0, 1)


def temp_at_pressure(press_bar: float) -> float:
    """Saturation temperature (°C) at pressure bar-a."""
    sorted_by_p = sorted(STEAM_TABLE, key=lambda r: r[1])
    return _interp(press_bar, sorted_by_p, 1, 0)


def latent_heat_at_temp(temp_c: float) -> float:
    """Latent heat of vaporization (kcal/kg) at temperature °C."""
    return _interp(temp_c, STEAM_TABLE, 0, 3)


def enthalpy_vapor_at_temp(temp_c: float) -> float:
    """Enthalpy of saturated vapor Hv (kcal/kg) at temperature °C."""
    return _interp(temp_c, STEAM_TABLE, 0, 4)


def vapor_density_at_temp(temp_c: float) -> float:
    """Saturated vapor density (kg/m³) at temperature °C."""
    return _interp(temp_c, STEAM_TABLE, 0, 2)


def specific_volume_at_temp(temp_c: float) -> float:
    """Specific volume of saturated vapor (m³/kg) at temperature °C."""
    rho = vapor_density_at_temp(temp_c)
    return 1.0 / rho if rho > 0 else 0.0
