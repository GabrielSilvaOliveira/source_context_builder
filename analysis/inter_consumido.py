"""Roda cmd_interaction usando o índice de TEXTO CONSUMIDO em vez do indexado."""
import sys, types
sys.path.insert(0,'.')
import lexical_overlap as lo
from consumed_index import build_consumed_index
lo.build_catalog_index = build_consumed_index   # monkeypatch
sys.argv = ['lexical_overlap.py'] + sys.argv[1:]
lo.main()
