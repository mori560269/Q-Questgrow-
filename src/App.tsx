import { useEffect } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Icon, type IconName } from "./components/Icon";
import { PwaStatus } from "./components/PwaBanners";
import { Toaster } from "./components/Toast";
import { useStore } from "./lib/store";
import { AssistantPage } from "./pages/Assistant";
import { ChatPage } from "./pages/Chat";
import { ConnectPage } from "./pages/Connect";
import { HomePage } from "./pages/Home";
import { MapPage } from "./pages/Map";
import { MePage } from "./pages/Me";
import { MyPlanPage } from "./pages/MyPlan";
import { NoticesPage } from "./pages/Notices";
import { OpsPage } from "./pages/Ops";
import { ProgramDetailPage } from "./pages/ProgramDetail";
import { ProgramsPage } from "./pages/Programs";

const TABS: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "ホーム", icon: "home" },
  { to: "/programs", label: "プログラム", icon: "calendar" },
  { to: "/map", label: "マップ", icon: "map" },
  { to: "/connect", label: "つながる", icon: "people" },
  { to: "/plan", label: "マイプラン", icon: "ticket" },
];

export function App() {
  const loc = useLocation();
  const nav = useNavigate();
  const role = useStore((s) => s.me.role);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [loc.pathname]);

  const tabs = role === "staff" ? [...TABS.slice(0, 4), { to: "/ops", label: "運営", icon: "shield" as IconName }] : TABS;
  const showFab = !["/assistant", "/ops"].includes(loc.pathname) && !loc.pathname.startsWith("/connect/");

  return (
    <div className="app">
      <Toaster />
      <PwaStatus />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/programs" element={<ProgramsPage />} />
        <Route path="/programs/:id" element={<ProgramDetailPage />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="/connect" element={<ConnectPage />} />
        <Route path="/connect/:id" element={<ChatPage />} />
        <Route path="/plan" element={<MyPlanPage />} />
        <Route path="/assistant" element={<AssistantPage />} />
        <Route path="/notices" element={<NoticesPage />} />
        <Route path="/me" element={<MePage />} />
        <Route path="/ops" element={<OpsPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>

      {showFab && (
        <button className="fab" onClick={() => nav("/assistant")} aria-label="AIコンシェルジュに質問">
          <Icon name="sparkle" size={26} />
        </button>
      )}

      <nav className="tabbar">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.to === "/"}>
            <Icon name={t.icon} size={24} />
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
