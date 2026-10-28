"""Detectores. Cada um recebe a conexão DuckDB com o modelo canônico e devolve tabelas.

Saída padrão: linhas de `flags` (contract_id, detector, score 0-1, flag, evidence JSON),
mais tabelas auxiliares próprias do detector (ex.: benford, item_overprice, community).
"""
