// 실 스키마의 ip.activity는 boolean이 아니라 ENUM('active'|'deactive').
export function isIpActive(ip) {
  return ip.activity === "active";
}
