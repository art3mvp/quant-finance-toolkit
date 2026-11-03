"""Simulación de Monte Carlo (movimiento browniano geométrico)."""

from __future__ import annotations

import math

import numpy as np


def _check_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} debe ser un entero >= 1, recibido {value!r}")


def _check_finite(name: str, value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} debe ser numérico, recibido {value!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} debe ser finito, recibido {value}")
    return value


def simulate_gbm(
    initial_value: float,
    mu: float,
    sigma: float,
    n_steps: int,
    n_simulations: int,
    seed: int | None = None,
) -> np.ndarray:
    """Simula trayectorias de un valor con movimiento browniano geométrico.

    Args:
        initial_value: Valor de partida (> 0 y finito).
        mu: Retorno esperado por periodo (finito).
        sigma: Volatilidad por periodo (finita y >= 0).
        n_steps: Horizonte temporal en periodos (entero >= 1).
        n_simulations: Número de trayectorias (entero >= 1).
        seed: Semilla para reproducibilidad.

    Returns:
        Array de forma ``(n_steps + 1, n_simulations)``; la fila 0 es ``initial_value``.

    Raises:
        ValueError: Si algún parámetro es inválido (NaN, infinito, fuera de rango).
    """
    _check_positive_int("n_steps", n_steps)
    _check_positive_int("n_simulations", n_simulations)
    initial_value = _check_finite("initial_value", initial_value)
    mu = _check_finite("mu", mu)
    sigma = _check_finite("sigma", sigma)
    if initial_value <= 0:
        raise ValueError(f"initial_value debe ser > 0, recibido {initial_value}")
    if sigma < 0:
        raise ValueError(f"sigma debe ser >= 0, recibido {sigma}")

    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_steps, n_simulations))
    log_steps = (mu - 0.5 * sigma**2) + sigma * z
    paths = initial_value * np.exp(np.cumsum(log_steps, axis=0))
    return np.vstack([np.full(n_simulations, initial_value), paths])