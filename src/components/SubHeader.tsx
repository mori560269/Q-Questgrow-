import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Icon } from "./Icon";

export function SubHeader({ title, right }: { title: string; right?: ReactNode }) {
  const nav = useNavigate();
  const loc = useLocation();
  return (
    <div className="subhead">
      <button className="icon-btn" onClick={() => (loc.key !== "default" ? nav(-1) : nav("/"))} aria-label="戻る">
        <Icon name="back" />
      </button>
      <h1>{title}</h1>
      {right}
    </div>
  );
}
