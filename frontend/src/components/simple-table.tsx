import type { ReactNode } from "react";

export interface SimpleTableColumn<Row> {
  key: string;
  header: string;
  render: (row: Row) => ReactNode;
}

export function SimpleTable<Row>({
  caption,
  columns,
  rows,
  getRowKey,
}: {
  caption: string;
  columns: Array<SimpleTableColumn<Row>>;
  rows: Row[];
  getRowKey: (row: Row, index: number) => string;
}) {
  return (
    <div className="table-scroll">
      <table className="simple-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.header}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={getRowKey(row, index)}>
              {columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
