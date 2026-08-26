export default function Pagination({ page, totalPages, totalItems, pageStart, pageSize, onPageChange }) {
  const pageEnd = Math.min(pageStart + pageSize, totalItems);

  return (
    <div className="mx-pagination">
      <span>
        전체 {totalItems}개 중 {pageStart + 1}~{pageEnd}개 표시
      </span>
      <button type="button" className="mx-btn mx-btn-secondary mx-pagination-btn" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        이전
      </button>
      <span>
        {page} / {totalPages}
      </span>
      <button type="button" className="mx-btn mx-btn-secondary mx-pagination-btn" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
        다음
      </button>
    </div>
  );
}
