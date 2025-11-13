import { Outlet } from "react-router-dom";
import Header from "../components/Header/Header";

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col font-display">
      <Header />
      <main className="grow">
        <Outlet /> 
      </main>
    </div>
  );
}
