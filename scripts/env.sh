#!/usr/bin/env bash
# Source this to put BalanceQueue's local toolchain on PATH.
#   source scripts/env.sh
#
# scripts/services.sh needs PostgreSQL 16 server binaries (initdb, pg_ctl, psql). They are
# looked up in this order: $BQ_PG_BIN, pg_ctl on PATH, then any micromamba env that has
# them (e.g. `micromamba create -n balancequeue -c conda-forge postgresql=16`).
# Set BQ_PGPORT to run the local cluster on a port other than 5434.
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/.local/opt/micromamba/root}"
if [ -z "${BQ_PG_BIN:-}" ]; then
  if command -v pg_ctl >/dev/null 2>&1; then
    BQ_PG_BIN="$(dirname "$(command -v pg_ctl)")"
  else
    for candidate in "$MAMBA_ROOT_PREFIX"/envs/*/bin; do
      if [ -x "$candidate/pg_ctl" ]; then
        BQ_PG_BIN="$candidate"
        break
      fi
    done
  fi
fi
export BQ_PG_BIN="${BQ_PG_BIN:-}"
export PATH="$HOME/.local/bin:${BQ_PG_BIN:+$BQ_PG_BIN:}$PATH"

export PGHOST=127.0.0.1
export PGPORT="${BQ_PGPORT:-5434}"
export PGUSER="${PGUSER:-$(whoami)}"
export PGDATABASE=balancequeue

export DATABASE_URL="postgresql+psycopg://$PGUSER@$PGHOST:$PGPORT/$PGDATABASE"
export TEST_DATABASE_URL="postgresql+psycopg://$PGUSER@$PGHOST:$PGPORT/balancequeue_test"
