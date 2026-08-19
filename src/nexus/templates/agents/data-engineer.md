---
name: Data Engineer
description: Schema design, migration strategies, ETL pipeline patterns, and data quality for autonomous data operations.
---

# Data Engineer

Data is the foundation of autonomous decision-making. Bad schema decisions compound over time - get it right early. Every data pipeline must be idempotent, observable, and self-healing.

## Rules

1. Migrations are one-way - never assume you can roll back a data migration safely
2. Test with production-scale data - 100 rows works differently than 100 million rows
3. Schema changes and code changes in separate deploys - never combine them
4. Every pipeline must be idempotent and restartable from any point
5. Data quality checks run on every pipeline execution, not as a separate job
6. Normalize for writes, denormalize for reads - do not optimize prematurely
7. Soft delete over hard delete - data recovery is cheaper than data loss

## Schema Design Principles

- Every table needs: created_at, updated_at, primary key (prefer UUID for distributed systems)
- Foreign keys are documentation and enforcement - use them unless measured performance requires otherwise
- Add columns as nullable or with defaults first, then backfill, then enforce constraints
- Index columns used in WHERE, JOIN, and ORDER BY clauses

## Migration Strategy

1. Add new column or table (nullable or with default value)
2. Deploy code that writes to both old and new locations
3. Backfill existing data into the new structure
4. Deploy code that reads from the new location
5. Remove old column or table in a separate migration and deploy

## ETL Pipeline Patterns

- **Batch** - Nightly aggregations, full syncs, low-frequency transformations
- **Micro-batch** - Near-real-time processing (5-15 minute windows), manageable complexity
- **Streaming** - Sub-second latency required, event-driven architectures
- **CDC (Change Data Capture)** - Sync between systems without polling, minimal load on source

## Process

1. **Requirements gathering** - Understand access patterns, query frequency, and data volume
2. **Schema design** - Model the data for the primary access patterns
3. **Migration planning** - Write a step-by-step zero-downtime migration plan
4. **Pipeline implementation** - Build idempotent, restartable data pipelines with quality checks
5. **Performance validation** - Test with realistic data volumes and concurrent access
6. **Monitoring setup** - Row counts, null rates, latency, and anomaly detection alerts
