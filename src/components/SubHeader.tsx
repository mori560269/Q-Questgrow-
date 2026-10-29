import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "./Icon";

export function SubHeader({ title, right }: { title: string; right?: ReactNode }) {
  const nav = useNavigate();
  return (
    <div className="subhead">
      <button className="icon-btn" onClick={() => (history.length > 1 ? nav(-1) : nav("/"))} aria-label="戻る">
        <Icon name="back" />
      </button>
      <h1>{title}</h1>
      {right}
    </div>
  );
}
