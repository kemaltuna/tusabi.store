# Medical Quiz App Scripts

## Unified Generation Workflow (NEW)

**Usage**:
All question generation is now handled by a single script:
```bash
python scripts/generate_batch.py --config configs/batches/<your_config>.yaml
```

**Workflow**:
1. Create a YAML config in `configs/batches/`.
2. Run `scripts/generate_batch.py`.
3. The script will:
   - Extract concepts from the source text.
   - Generate questions using `GenerationEngine`.
   - Validate and ingest them into the DB.
   - Print evidence of success.

**Legacy Scripts**:
> [!WARNING]
> Do **NOT** create `add_*_batch*.py` scripts anymore. They are deprecated and will be deleted by the guardrail.

## Helper Scripts
- `check_clean_code.py`: Guardrail script to enforce coding standards (No 'null', no legacy scripts).
