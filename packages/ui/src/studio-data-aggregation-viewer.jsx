"use client";

import { useMemo, useState } from "react";
import { msg } from "./studio-messages.ko.js";

// 데이터 집계 보기(WO-N9). 판 내용(body)의 집계표·차트 정의·칸별 계산 근거만 그린다.
// 숫자는 서버가 저장한 문자열(value)과 표시 문자열(display)을 그대로 쓰고, 화면에서 숫자를 새로 만들지 않는다.
// 차트 좌표를 계산할 때만 value를 Number로 바꾼다. 외부 라이브러리·외부 자원은 쓰지 않는다.

const SEPARATOR = " · ";
const RANGE_PREVIEW = 3;
export const CHART_SIZE = Object.freeze({ width: 560, height: 240, left: 16, right: 16, top: 16, bottom: 44 });

const asArray = (value) => (Array.isArray(value) ? value : []);
const computedRole = (column) => column?.role === "measure" || column?.role === "growth";

/** 경고를 "하지 않은 요청"과 그 밖의 알림으로 나눈다(서버 문구의 앞머리 "하지 않은 요청: "는 떼고 보인다). */
export function splitWarnings(warnings = []) {
  const prefix = `${msg("studio.aggregation.skipped")}: `;
  const skipped = [];
  const notes = [];
  for (const text of asArray(warnings)) {
    const value = String(text ?? "");
    if (value.startsWith(prefix)) skipped.push(value.slice(prefix.length));
    else notes.push(value);
  }
  return { skipped, notes };
}

/** 차트 점 → 집계표의 같은 칸 표시 문자열. 막대는 행 순서, 선은 (월, 묶음 표시) 일치로 찾는다. 못 찾으면 null. */
export function chartDisplayLookup(body = {}) {
  const chart = body.chart;
  const columns = asArray(body.columns);
  const rows = asArray(body.rows);
  const measureIdx = columns.findIndex((column) => column?.role === "measure");
  const groupIdx = columns.map((column, index) => (column?.role === "group" ? index : -1)).filter((index) => index >= 0);
  if (!chart || measureIdx < 0) return () => null;
  if (chart.kind === "bar") return (_series, index) => rows[index]?.[measureIdx]?.display ?? null;
  const monthIdx = columns.findIndex((column) => column?.key === chart.x_key);
  const seriesIdx = groupIdx.filter((index) => index !== monthIdx);
  return (series, _index, point) => {
    const row = rows.find((cells) => cells?.[monthIdx]?.value === point?.x
      && (seriesIdx.length === 0 || seriesIdx.map((index) => cells?.[index]?.display ?? "").join(SEPARATOR) === series?.label));
    return row?.[measureIdx]?.display ?? null;
  };
}

/** 차트 그림 모델(순수 함수). 점의 값은 point.value 문자열 그대로 들고 다닌다. null은 빈 막대·끊긴 점. */
export function chartModel(chart, size = CHART_SIZE) {
  if (!chart || !["bar", "line"].includes(chart.kind)) return null;
  const series = asArray(chart.series);
  const numbers = series.flatMap((item) => asArray(item?.points)).map((point) => (point?.value === null || point?.value === undefined ? NaN : Number(point.value))).filter(Number.isFinite);
  let low = Math.min(0, ...numbers);
  let high = Math.max(0, ...numbers);
  if (high === low) high = low + 1;
  const plotW = size.width - size.left - size.right;
  const plotH = size.height - size.top - size.bottom;
  const y = (value) => size.top + ((high - value) / (high - low)) * plotH;
  const baseline = y(0);
  const xs = asArray(series[0]?.points).map((point) => point?.x);
  const band = xs.length ? plotW / xs.length : plotW;
  const center = (index) => size.left + band * index + band / 2;
  const marks = [];
  let gap = false;
  series.forEach((item, s) => asArray(item?.points).forEach((point, index) => {
    const raw = point?.value;
    const number = raw === null || raw === undefined ? NaN : Number(raw);
    if (!Number.isFinite(number)) { gap = true; marks.push({ series: s, index, x: point?.x, value: null, empty: true, cx: center(index), cy: baseline }); return; }
    const mark = { series: s, index, x: point?.x, value: String(raw), empty: false, cx: center(index), cy: y(number) };
    if (chart.kind === "bar") {
      const width = Math.max(2, band * 0.6);
      mark.rect = { x: center(index) - width / 2, y: Math.min(mark.cy, baseline), width, height: Math.max(1, Math.abs(mark.cy - baseline)) };
    }
    marks.push(mark);
  }));
  // 선: null에서 끊어 이어진 구간마다 하나의 선을 그린다.
  const lines = chart.kind === "line" ? series.map((item, s) => {
    const segments = [];
    let current = [];
    for (const mark of marks.filter((m) => m.series === s)) {
      if (mark.empty) { if (current.length) segments.push(current); current = []; } else current.push(mark);
    }
    if (current.length) segments.push(current);
    return segments.map((segment) => segment.map((m) => `${m.cx.toFixed(1)},${m.cy.toFixed(1)}`).join(" "));
  }) : [];
  return { kind: chart.kind, size, baseline, xs, band, center, marks, lines, gap };
}

const shortLabel = (text) => { const value = String(text ?? ""); return value.length > 10 ? `${value.slice(0, 9)}…` : value; };

export function AggregationChart({ body }) {
  const chart = body?.chart;
  const model = useMemo(() => chartModel(chart), [chart]);
  const lookup = useMemo(() => chartDisplayLookup(body), [body]);
  if (!model) return null;
  const { size } = model;
  const series = asArray(chart.series);
  const label = (mark) => {
    const item = series[mark.series];
    const point = asArray(item?.points)[mark.index];
    const shown = mark.empty ? msg("studio.aggregation.not_computable") : (lookup(item, mark.index, point) ?? mark.value);
    return `${series.length > 1 ? `${item?.label ?? ""}${SEPARATOR}` : ""}${mark.x ?? ""}: ${shown}`;
  };
  return <figure className="studio-aggregation__chart" data-chart-kind={model.kind}>
    <svg viewBox={`0 0 ${size.width} ${size.height}`} role="img" aria-label={`${msg("studio.aggregation.chart")}: ${chart.x_label ?? ""}`} preserveAspectRatio="xMidYMid meet">
      <line className="studio-aggregation__axis" x1={size.left} x2={size.width - size.right} y1={model.baseline} y2={model.baseline} />
      {model.xs.map((x, index) => <text key={`x-${index}`} className="studio-aggregation__tick" x={model.center(index)} y={size.height - size.bottom + 16} textAnchor="middle">
        <title>{String(x ?? "")}</title>{shortLabel(x)}</text>)}
      {model.lines.map((segments, s) => segments.map((points, index) => <polyline key={`l-${s}-${index}`} className={`studio-aggregation__line studio-aggregation__series-${s % 4}`} points={points} fill="none" />))}
      {model.marks.map((mark) => {
        const key = `${mark.series}-${mark.index}`;
        const common = { "data-series": String(mark.series), "data-x": String(mark.x ?? ""), "data-value": mark.value ?? "", "data-empty": mark.empty ? "true" : undefined };
        if (model.kind === "bar") {
          return mark.empty
            ? <rect key={key} {...common} className="studio-aggregation__bar studio-aggregation__bar--empty" x={mark.cx - Math.max(2, model.band * 0.3)} y={model.baseline - 6} width={Math.max(4, model.band * 0.6)} height={6}><title>{label(mark)}</title></rect>
            : <rect key={key} {...common} className="studio-aggregation__bar studio-aggregation__series-0" {...mark.rect}><title>{label(mark)}</title></rect>;
        }
        return mark.empty ? null : <circle key={key} {...common} className={`studio-aggregation__point studio-aggregation__series-${mark.series % 4}`} cx={mark.cx} cy={mark.cy} r={3.5}><title>{label(mark)}</title></circle>;
      })}
    </svg>
    <figcaption className="studio-aggregation__legend">
      {series.map((item, s) => <span key={s} className="studio-aggregation__legend-item"><span className={`studio-aggregation__swatch studio-aggregation__series-${s % 4}`} aria-hidden="true" />{item?.label ?? ""}</span>)}
      {model.gap && <span className="studio-aggregation__legend-item" data-gap="true">{msg("studio.aggregation.chart.gap")}</span>}
    </figcaption>
  </figure>;
}

function RangeList({ ranges }) {
  const [open, setOpen] = useState(false);
  if (ranges.length === 0) return <dd>-</dd>;
  if (ranges.length <= RANGE_PREVIEW) return <dd><ul className="studio-aggregation__ranges">{ranges.map((text, index) => <li key={index}>{text}</li>)}</ul></dd>;
  return <dd>
    <span>{msg("studio.aggregation.evidence.ranges_count", { n: ranges.length })}</span>{" "}
    <button type="button" className="studio-btn" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{msg(open ? "studio.aggregation.evidence.collapse" : "studio.aggregation.evidence.expand")}</button>
    {open && <ul className="studio-aggregation__ranges">{ranges.map((text, index) => <li key={index}>{text}</li>)}</ul>}
  </dd>;
}

export function EvidencePane({ body, selected }) {
  const columns = asArray(body?.columns);
  const row = selected ? asArray(body?.rows)[selected.row] : null;
  const cell = row ? row[selected.col] : null;
  const column = selected ? columns[selected.col] : null;
  if (!cell || !column) return <p className="studio-aggregation__hint">{msg("studio.aggregation.evidence.pick")}</p>;
  if (!computedRole(column)) return <div data-evidence-cell=""><h4>{column.label}: {cell.display}</h4><p>{msg("studio.aggregation.evidence.original")}</p></div>;
  const entry = body?.evidence?.[cell.evidence_id] ?? null;
  const ok = cell.status === "ok" && cell.value !== null && cell.value !== undefined;
  const source = body?.source ?? {};
  const groups = columns.map((item, index) => (item?.role === "group" ? `${item.label} = ${row[index]?.display ?? ""}` : null)).filter(Boolean);
  return <div data-evidence-cell="" data-evidence-id={cell.evidence_id ?? undefined}>
    <h4>{column.label}{groups.length ? ` (${groups.join(SEPARATOR)})` : ""}</h4>
    <p className="studio-aggregation__value"><strong>{ok ? cell.display : msg("studio.aggregation.not_computable")}</strong>{" "}
      <span className="studio-aggregation__mark">{msg("studio.aggregation.computed")}</span></p>
    <dl className="studio-aggregation__facts">
      {!ok && cell.reason && <><dt>{msg("studio.aggregation.evidence.reason")}</dt><dd>{cell.reason}</dd></>}
      <dt>{msg("studio.aggregation.evidence.file")}</dt><dd>{source.file_name ?? ""}{source.sheet ? `${SEPARATOR}${source.sheet}` : ""}</dd>
      {entry && <>
        <dt>{msg("studio.aggregation.evidence.ranges")}</dt><RangeList key={cell.evidence_id} ranges={asArray(entry.ranges).map(String)} />
        <dt>{msg("studio.aggregation.evidence.filter")}</dt><dd>{entry.filter_text ?? ""}</dd>
        <dt>{msg("studio.aggregation.evidence.formula")}</dt><dd>{entry.formula ?? ""}</dd>
        <dt>{msg("studio.aggregation.evidence.row_count")}</dt><dd data-row-count="">{String(entry.row_count ?? "")}</dd>
        <dd className="studio-aggregation__excluded">{msg("studio.aggregation.evidence.excluded", { not_number: entry.excluded?.not_number ?? 0, blank: entry.excluded?.blank ?? 0 })}</dd>
      </>}
    </dl>
  </div>;
}

export function DataAggregationViewer({ content }) {
  const body = content?.body ?? {};
  const columns = asArray(body.columns);
  const rows = asArray(body.rows);
  const { skipped, notes } = useMemo(() => splitWarnings(body.warnings), [body.warnings]);
  const [selected, setSelected] = useState(null);
  return <div className="studio-aggregation">
    <div className="studio-aggregation__main">
      {body.conditions_text && <section className="studio-aggregation__conditions">
        <h3>{msg("studio.aggregation.conditions")}</h3><p>{body.conditions_text}</p>
      </section>}
      {skipped.length > 0 && <section className="studio-aggregation__skipped" role="note">
        <h3>{msg("studio.aggregation.skipped")}</h3><ul>{skipped.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </section>}
      {notes.length > 0 && <section className="studio-aggregation__notes">
        <h3>{msg("studio.aggregation.warnings")}</h3><ul>{notes.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </section>}
      {asArray(body.summary).length > 0 && <section className="studio-aggregation__summary">
        <h3>{msg("studio.aggregation.summary")}</h3><ul>{body.summary.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </section>}
      <div className="studio-aggregation__table" role="region" aria-label={msg("studio.aggregation.table")} tabIndex={0}>
        <table>
          <thead><tr>{columns.map((column, index) => <th key={index} scope="col" data-role={column?.role}>{column?.label ?? ""}</th>)}</tr></thead>
          <tbody>{rows.map((cells, r) => <tr key={r}>{columns.map((column, c) => {
            const cell = asArray(cells)[c] ?? {};
            const isSelected = selected?.row === r && selected?.col === c;
            if (!computedRole(column)) {
              return <td key={c} data-computed="false"><button type="button" className="studio-aggregation__cell" aria-pressed={isSelected} onClick={() => setSelected({ row: r, col: c })}>{cell.display ?? ""}</button></td>;
            }
            const ok = cell.status === "ok" && cell.value !== null && cell.value !== undefined;
            return <td key={c} data-computed="true" data-status={cell.status ?? ""}>
              <button type="button" className="studio-aggregation__cell" aria-pressed={isSelected} onClick={() => setSelected({ row: r, col: c })}>
                {ok ? <span className="studio-aggregation__number">{cell.display}</span>
                  : <span className="studio-aggregation__failed">{msg("studio.aggregation.not_computable")}{cell.reason ? <small>{cell.reason}</small> : null}</span>}
                <span className="studio-aggregation__mark">{msg("studio.aggregation.computed")}</span>
              </button>
            </td>;
          })}</tr>)}</tbody>
        </table>
      </div>
      {body.chart && <AggregationChart body={body} />}
    </div>
    <aside className="studio-aggregation__evidence" aria-label={msg("studio.aggregation.evidence")}>
      <h3>{msg("studio.aggregation.evidence")}</h3>
      <EvidencePane body={body} selected={selected} />
    </aside>
  </div>;
}

export default DataAggregationViewer;

/** 소스 목록 줄의 "집계 전용" 표지(질문 근거에서 빠지고 데이터 집계에만 쓰는 큰 표). */
export function AggregationOnlyBadge() {
  return <span className="source-aggregation-only" data-aggregation-only="">{msg("source.aggregation_only")}</span>;
}
