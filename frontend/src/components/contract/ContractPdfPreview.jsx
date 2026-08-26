import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export default function ContractPdfPreview({ pdfUrl, rawText }) {
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);

  if (!pdfUrl) return <div className="preview-fallback-text">{rawText ? rawText.slice(0, 1200) : "원문 텍스트가 없습니다."}</div>;

  const goPrev = () => setPageNumber((page) => Math.max(1, page - 1));
  const goNext = () => setPageNumber((page) => Math.min(numPages ?? page, page + 1));
  return (
    <div className="preview-pdf">
      <div className="preview-pdf-row">
        {numPages > 1 && <button type="button" className="preview-pdf-arrow preview-pdf-arrow--prev" disabled={pageNumber <= 1} onClick={goPrev} aria-label="이전 쪽">‹</button>}
        <div className="preview-pdf-page">
          <Document file={pdfUrl} onLoadSuccess={({ numPages: total }) => { setNumPages(total); setPageNumber(1); }} loading={<p className="preview-fallback-text">PDF 불러오는 중…</p>} error={<p className="preview-fallback-text">PDF를 불러오지 못했습니다.</p>}>
            <Page pageNumber={pageNumber} width={760} />
          </Document>
        </div>
        {numPages > 1 && <button type="button" className="preview-pdf-arrow preview-pdf-arrow--next" disabled={pageNumber >= numPages} onClick={goNext} aria-label="다음 쪽">›</button>}
      </div>
      {numPages > 1 && <div className="preview-pdf-nav"><button type="button" className="preview-header-btn" disabled={pageNumber <= 1} onClick={goPrev}>‹ 이전</button><span className="mx-mono">{pageNumber} / {numPages}쪽</span><button type="button" className="preview-header-btn" disabled={pageNumber >= numPages} onClick={goNext}>다음 ›</button></div>}
    </div>
  );
}
