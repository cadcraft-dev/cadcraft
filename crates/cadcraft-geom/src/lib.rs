//! CadCraft geometry core (WASM-ready, no_std-friendly math only).
//! Mirrors Python verifier/tolerance.py: tol = min_edge/1000.

/// Tolerance rule from Pointer-CAD v2 notes: min bbox edge / 1000.
pub fn tolerance(x0: f64, y0: f64, x1: f64, y1: f64) -> f64 {
    let w = (x1 - x0).abs().max(1e-9);
    let h = (y1 - y0).abs().max(1e-9);
    w.min(h) / 1000.0
}

/// Absolute check used by verifier.
pub fn within(a: f64, b: f64, tol: f64) -> bool {
    (a - b).abs() <= tol.max(1e-9)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tol_80x50_is_0_05() {
        assert!((tolerance(0.0, 0.0, 80.0, 50.0) - 0.05).abs() < 1e-12);
    }
    #[test]
    fn rect_check() {
        assert!(within(80.0, 80.0, 0.05));
        assert!(!within(80.5, 80.0, 0.05));
    }
}
