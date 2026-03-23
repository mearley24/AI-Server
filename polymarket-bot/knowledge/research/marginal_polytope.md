# Marginal Polytope — Cross-Market Arbitrage Geometry

> Type: research
> Tags: arbitrage, cross-market, convex-hull, geometry, Gurobi, advanced, ramperxx
> Created: 2026-03-23
> Updated: 2026-03-23
> Confidence: low
> Status: active

## Summary
Advanced cross-market arbitrage technique using convex hull geometry to find mispricings across correlated prediction market contracts. Based on ramperxx's research. Requires Python + Gurobi optimizer. Not yet implemented.

## Key Facts
- Uses marginal polytope theory to model valid probability distributions across correlated markets
- When market prices fall outside the convex hull of valid distributions, arbitrage exists
- Requires Gurobi optimizer (commercial, free academic license) for linear programming
- Source: ramperxx's research and open-source implementation
- Applicable to correlated markets across Polymarket and potentially Kalshi
- Implementation complexity: high — requires understanding of convex optimization
- Not yet implemented in our trading bot — filed as future research

## Numbers
- **optimizer**: Gurobi (LP solver)
- **language**: Python
- **complexity**: High
- **implementation_status**: Not started

## Links
- Related: [[strategies/sports_patterns.md]]
- Related: [[markets/polymarket_markets.md]]

## Raw Notes
The marginal polytope approach is a mathematically rigorous way to find arbitrage opportunities
that simpler methods (like YES+YES < $1.00) miss. Key concepts:

1. Each prediction market outcome defines a dimension
2. Valid probability distributions form a convex polytope in this space
3. Market prices represent a point in this space
4. If the point is outside the polytope, guaranteed profit exists
5. The LP solver finds the optimal arbitrage portfolio

This is significantly more sophisticated than our current sports_arb approach but could find
opportunities in correlated multi-outcome markets that simple pairwise checks miss.

Challenges:
- Gurobi licensing and deployment
- Real-time computation speed (LP solve for each market scan)
- Market execution speed (need to fill multiple orders simultaneously)
- Data quality (need accurate orderbook data across many markets)

## Action Items
- [ ] Review ramperxx's implementation for feasibility assessment
- [ ] Evaluate Gurobi licensing options (academic vs commercial)
- [ ] Identify specific Polymarket market clusters where this could apply
- [ ] Prototype with small market set to validate the approach
