import type { ChartSpecification } from "@leitesol/contracts";

const width = 720;
const height = 320;
const margin = { top: 18, right: 20, bottom: 58, left: 70 };
const colors = ["#ffd08c", "#77d6a0", "#ff9c63", "#8bb8ff"];
const numberFormat = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 0,
});

export const MonthlySeriesChart = ({
  chart,
}: {
  chart: ChartSpecification;
}) => {
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = chart.series.flatMap((series) =>
    series.values.filter((value): value is number => value !== null),
  );
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const range = maximum - minimum || 1;
  const xFor = (index: number) =>
    margin.left +
    (chart.categories.length > 1
      ? (index / (chart.categories.length - 1)) * plotWidth
      : plotWidth / 2);
  const yFor = (value: number) =>
    margin.top + ((maximum - value) / range) * plotHeight;
  const ticks = Array.from({ length: 5 }, (_, index) =>
    minimum + (range * index) / 4,
  );

  return (
    <section className="monthly-chart" aria-label={chart.title}>
      <h3>{chart.title}</h3>
      <div className="monthly-chart-scroll">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`${chart.title}. Eixo horizontal: ${chart.xAxis.label}. Eixo vertical: ${chart.yAxis.label}.`}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={margin.left}
                x2={width - margin.right}
                y1={yFor(tick)}
                y2={yFor(tick)}
                className="chart-grid-line"
              />
              <text
                x={margin.left - 8}
                y={yFor(tick) + 4}
                textAnchor="end"
                className="chart-axis-text"
              >
                {numberFormat.format(tick)}
              </text>
            </g>
          ))}

          {chart.series.map((series, seriesIndex) => {
            const points = series.values
              .map((value, index) =>
                value === null ? null : `${xFor(index)},${yFor(value)}`,
              )
              .filter((point): point is string => point !== null)
              .join(" ");

            return (
              <g key={series.name}>
                <polyline
                  points={points}
                  fill="none"
                  stroke={colors[seriesIndex % colors.length]}
                  strokeWidth="3"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {series.values.map((value, index) =>
                  value === null ? null : (
                    <circle
                      key={`${series.name}-${index}`}
                      cx={xFor(index)}
                      cy={yFor(value)}
                      r="4"
                      fill={colors[seriesIndex % colors.length]}
                    >
                      <title>
                        {chart.categories[index]}: {numberFormat.format(value)}
                      </title>
                    </circle>
                  ),
                )}
              </g>
            );
          })}

          {chart.categories.map((category, index) => (
            <text
              key={`${category}-${index}`}
              x={xFor(index)}
              y={height - margin.bottom + 20}
              textAnchor="middle"
              className="chart-axis-text"
            >
              {category}
            </text>
          ))}
        </svg>
      </div>
      <div className="chart-legend" aria-label="Séries">
        {chart.series.map((series, index) => (
          <span key={series.name}>
            <i style={{ backgroundColor: colors[index % colors.length] }} />
            {series.name}
          </span>
        ))}
      </div>
    </section>
  );
};
