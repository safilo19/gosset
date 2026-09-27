"""Tier A: tests against the NIST/ITL Statistical Reference Datasets.

StRD exists for exactly this purpose — NIST publishes datasets together with certified values
computed in multiple-precision arithmetic and rounded to 15 significant digits, so a statistics
package can be checked against an authority rather than against itself. The collections used here:

* Univariate Summary Statistics — mean, standard deviation, lag-1 autocorrelation
* Linear Least Squares Regression — coefficients and their SDs, residual SD, R², the ANOVA table
* Analysis of Variance — one-way df/SS/MS/F, R², residual SD

The sets are graded Lower / Average / Higher difficulty on purpose. The Higher ones (Filip,
Wampler4-5, Longley, SmLs07-09, AtmWtAg) are near-collinear or carry many constant leading digits;
they are where a solver's conditioning shows, and where this suite records the digits achieved
instead of pretending to full precision.
"""
