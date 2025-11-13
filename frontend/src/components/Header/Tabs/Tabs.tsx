import { useMemo } from "react";
import WorkIcon from "@mui/icons-material/Work";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import ApartmentIcon from '@mui/icons-material/Apartment';
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

export default function Tabs() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();

  const tabs = useMemo(() => {
    const tabs = [
      {
        label: t("companies"),
        icon: <ApartmentIcon fontSize="large" />,
        value: "companies",
      },
      {
        label: t("jobs"),
        icon: <WorkIcon fontSize="large" />,
        value: "jobs",
      },
      {
        label: t("applied"),
        icon: <CheckCircleIcon fontSize="large" />,
        value: "applied-jobs",
      },
      {
        label: t("notInterested"),
        icon: <CancelIcon fontSize="large" />,
        value: "not-interested-jobs",
      },
    ];

    return tabs;
  }, [t]);

  const activeTab = useMemo(() => {
    return location.pathname.replace("/", "") || "jobs";
  }, [location.pathname]);

  const onTabChange = (value: string) => {
    const path = value.startsWith("/") ? value : `/${value}`;
    navigate(path);
  };

  return (
    <div className="py-8">
      <div className="px-4 mx-auto sm:px-6 lg:px-8 max-w-7xl">
        <div className="flex items-center justify-center">
          <nav className="flex flex-wrap justify-center gap-4">
            {tabs.map((tab, index) => {
              const isActive = activeTab === tab.value;
              return (
                <button
                  key={index}
                  onClick={() => onTabChange(tab.value)}
                  className={`cursor-pointer inline-flex items-center px-4 py-2 rounded-lg text-xl font-semibold transition-all duration-200
                    ${
                      isActive
                        ? "bg-yellow-300 text-blue-dark shadow-md"
                        : "bg-gray-100 text-gray-600 hover:bg-yellow-200 hover:text-blue-dark"
                    }
                  `}
                >
                  <span
                    className={`flex items-center transition-colors ${
                      isActive
                        ? "text-blue-dark"
                        : "text-gray-500 group-hover:text-blue-dark"
                    }`}
                  >
                    {tab.icon}
                  </span>
                  <span className="ml-2">{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </div>
    </div>
  );
}
