import * as Select from "@radix-ui/react-select";

// 네이티브 <select>는 팝업 위치를 브라우저가 정해서(선택된 항목 기준 정렬) 트리거 위로
// 뜨거나 어긋날 수 있다. Radix Select로 교체해 위치/키보드 내비게이션/접근성을 라이브러리에
// 맡기고, 여기서는 mx-* 톤에 맞춘 스타일만 입힌다.
export default function CustomSelect({ value, options, onChange, ariaLabel, placeholder, disabled = false }) {
  const current = options.find((o) => String(o.value) === String(value));

  return (
    <Select.Root value={String(value)} onValueChange={(v) => onChange(coerce(v, options))} disabled={disabled}>
      <Select.Trigger className="mx-input mx-select-trigger" aria-label={ariaLabel}>
        <Select.Value placeholder={placeholder ?? current?.label}>{current?.label}</Select.Value>
        <Select.Icon className="mx-select-chevron">▾</Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="mx-select-menu" position="popper" sideOffset={4}>
          <Select.Viewport>
            {options.map((o) => (
              <Select.Item key={o.value} value={String(o.value)} className="mx-select-option">
                <Select.ItemText>{o.label}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

// Radix Select 값은 항상 문자열이다 — 원래 옵션의 value 타입(숫자 등)으로 되돌려서 onChange에 넘긴다.
function coerce(stringValue, options) {
  const match = options.find((o) => String(o.value) === stringValue);
  return match ? match.value : stringValue;
}
