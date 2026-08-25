// POST /ips가 409 DUPLICATE_IP로 응답했을 때(API 명세서 #13 "구현 시 주의" — 같은 정규화
// 키의 IP가 이미 있으면 409 + 기존 ipId) 보여주는 복구 모달. 중복 생성 대신 기존 IP를
// 그대로 선택할 수 있게 하는 게 목적이라, 빨간 에러 배너로 뭉뚱그리지 않는다.
export default function DuplicateIpPrompt({ title, onUseExisting, onCancel }) {
  return (
    <div className="detail-pin-wrap detail-extend-overlay" onClick={onCancel}>
      <div className="mx-card mx-card-pad detail-pin-modal" onClick={(e) => e.stopPropagation()}>
        <h4 className="mx-heading-card">이미 등록된 IP가 있습니다</h4>
        <p className="mx-text-sm mx-muted">
          "<b>{title}</b>"와(과) 같은 이름의 IP가 이미 있습니다. 새로 만드는 대신 기존 IP를 사용하시겠습니까?
        </p>
        <div className="detail-pin-actions">
          <button type="button" className="mx-btn mx-btn-secondary" onClick={onCancel}>
            취소
          </button>
          <button type="button" className="mx-btn mx-btn-primary" onClick={onUseExisting}>
            기존 IP 사용
          </button>
        </div>
      </div>
    </div>
  );
}
