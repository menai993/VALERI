"""Semantic layer (M3): the metric registry + validated query builder.

The only sanctioned way for higher layers (tools in M9, NL→SQL later) to run
metric queries: registered metrics only, validated bind parameters only.
The model never writes SQL; it can only name a registered metric.
"""
