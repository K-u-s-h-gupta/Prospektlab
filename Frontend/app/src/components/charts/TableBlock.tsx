import React from 'react';

interface TableBlockProps {
  headers: string[];
  rows: string[][];
  title?: string;
}

export const TableBlock: React.FC<TableBlockProps> = ({ headers, rows, title }) => {
  if (!headers.length || !rows.length) return null;

  return (
    <div className="glass" style={{
      background: 'rgba(15, 23, 42, 0.45)',
      border: '1px solid rgba(255, 255, 255, 0.08)',
      borderRadius: '8px',
      margin: '12px 0',
      width: '100%',
      overflow: 'hidden'
    }}>
      {/* Horizontal scroll wrapper for narrow screens (mobile/tablet) */}
      <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
      {title && (
        <div style={{
          padding: '10px 14px',
          fontSize: '12.5px',
          fontWeight: 700,
          color: 'var(--text-primary)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          background: 'rgba(3, 7, 18, 0.3)'
        }}>
          {title}
        </div>
      )}
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: '12px',
        textAlign: 'left',
        minWidth: '420px'
      }}>
        <thead>
          <tr style={{
            borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
            backgroundColor: 'rgba(3, 7, 18, 0.25)'
          }}>
            {headers.map((h, i) => (
              <th key={i} style={{
                padding: '8px 10px',
                color: 'var(--text-secondary)',
                fontWeight: 600,
                fontSize: '10.5px',
                textTransform: 'uppercase',
                letterSpacing: '0.03em',
                minWidth: i === 0 ? '110px' : '70px',
                whiteSpace: 'normal',
                wordBreak: 'break-word'
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{
              borderBottom: i < rows.length - 1 ? '1px solid rgba(255, 255, 255, 0.04)' : 'none',
              transition: 'background-color 0.15s ease'
            }}
            onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.015)'}
            onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
            >
              {row.map((cell, j) => (
                <td key={j} style={{
                  padding: '8px 10px',
                  color: 'var(--text-primary)',
                  fontFamily: j === 0 ? 'inherit' : 'var(--font-mono)',
                  fontWeight: j === 0 ? 600 : 400,
                  fontSize: j === 0 ? '11.5px' : '11px',
                  minWidth: j === 0 ? '110px' : '70px',
                  whiteSpace: 'normal',
                  wordBreak: 'break-word',
                  overflowWrap: 'anywhere'
                }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
};

export default TableBlock;
