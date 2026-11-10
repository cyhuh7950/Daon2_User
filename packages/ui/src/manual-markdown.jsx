// 앱 안 매뉴얼 보기: 검증된 Release Markdown을 제목·목록·표·그림으로 그린다.
// 그림은 공개 사본의 /manual/images/ 안 PNG만 그린다(다른 경로는 설명 글만 보인다).
const SAFE_IMAGE = /^images\/[a-z0-9-]+\.png$/u;

export function readableManualLine(line) {
  return line
    .replace(/!\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/\*\*([^*]+)\*\*/gu, "$1")
    .replace(/`([^`]+)`/gu, "$1");
}

function tableCells(line) {
  const cells = [];
  let current = "";
  const body = line.trim().replace(/^\|/u, "");
  for (let index = 0; index < body.length; index += 1) {
    if (body[index] === "\\" && body[index + 1] === "|") {
      current += "|";
      index += 1;
    } else if (body[index] === "|") {
      cells.push(current);
      current = "";
    } else current += body[index];
  }
  if (current.trim()) cells.push(current);
  return cells.map((cell) => readableManualLine(cell.trim()));
}

const isDivider = (cells) => cells.every((cell) => /^:?-{3,}:?$/u.test(cell));

function ManualTable({ lines }) {
  const rows = lines.map(tableCells).filter((cells) => !isDivider(cells));
  const [head, ...body] = rows;
  return <div className="manual-reader-table"><table>
    <thead><tr>{head.map((cell, index) => <th key={index} scope="col">{cell}</th>)}</tr></thead>
    <tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody>
  </table></div>;
}

function ManualImage({ line, index }) {
  const match = /^!\[([^\]]+)\]\(([^)]+)\)$/u.exec(line);
  const alt = match ? match[1] : readableManualLine(line);
  if (!match || !SAFE_IMAGE.test(match[2])) return <p className="manual-reader-caption" key={index}>{alt}</p>;
  return <figure className="manual-reader-figure" key={index}>
    <img src={`/manual/${match[2]}`} alt={alt} loading="lazy" />
    <figcaption>{alt}</figcaption>
  </figure>;
}

export function ManualMarkdown({ text }) {
  const lines = text.split("\n");
  const blocks = [];
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index].trim();
    if (raw.startsWith("|")) {
      const start = index;
      while (index + 1 < lines.length && lines[index + 1].trim().startsWith("|")) index += 1;
      blocks.push(<ManualTable key={start} lines={lines.slice(start, index + 1)} />);
      continue;
    }
    if (/^!\[/u.test(raw)) {
      blocks.push(<ManualImage key={index} line={raw} index={index} />);
      continue;
    }
    const value = readableManualLine(raw);
    if (!value) {
      blocks.push(<span className="manual-reader-space" aria-hidden="true" key={index} />);
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/u.exec(value);
    if (heading) {
      const level = heading[1].length;
      blocks.push(level === 1 ? <h3 key={index}>{heading[2]}</h3> : level === 4 ? <h5 key={index}>{heading[2]}</h5> : <h4 key={index}>{heading[2]}</h4>);
      continue;
    }
    const ordered = /^\d+\.\s+(.+)$/u.exec(value);
    if (ordered) {
      blocks.push(<p className="manual-reader-list" key={index}><span>{value.slice(0, value.indexOf(" "))}</span>{ordered[1]}</p>);
      continue;
    }
    const bullet = /^-\s+(.+)$/u.exec(value);
    if (bullet) {
      blocks.push(<p className="manual-reader-list" key={index}><span>•</span>{bullet[1]}</p>);
      continue;
    }
    blocks.push(value.startsWith("> ") ? <aside key={index}>{value.slice(2)}</aside> : <p key={index}>{value}</p>);
  }
  return <div className="manual-reader-body">{blocks}</div>;
}

export default ManualMarkdown;
