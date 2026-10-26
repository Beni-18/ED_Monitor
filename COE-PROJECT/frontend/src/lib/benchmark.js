// A benchmark run where too many LLM calls failed is a biased sample, not a result.
export const MIN_COVERAGE = 0.9;

export const coverageOf = (set) => {
  const total = set?.total_patients;
  if (!total) return 1;
  return (set.evaluated ?? total) / total;
};

/**
 * Pick the benchmark to headline from /api/metrics. The hold-out set is the
 * unbiased figure; fall back to the development set for older result files.
 * `incomplete` is true when fewer than MIN_COVERAGE of patients were evaluated.
 */
export function pickBenchmark(metrics) {
  const exp = metrics?.experiment;
  const set = exp?.holdout?.ai ? exp.holdout : exp?.ai ? exp : null;
  if (!set) return { label: null, data: null, hasHoldout: false, incomplete: false };
  return {
    label: set === exp ? 'DEV SET' : 'HOLD-OUT SET',
    data: set,
    hasHoldout: set !== exp,
    incomplete: coverageOf(set) < MIN_COVERAGE,
  };
}
