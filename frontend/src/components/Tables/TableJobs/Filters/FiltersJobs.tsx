import Select, { type SingleValue, components } from "react-select";
import { Building2 } from "lucide-react";
import type { ControlProps } from "react-select";
import { Briefcase, Globe, Map } from "lucide-react";
import { useMemo, type Dispatch, type SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { allCountries } from "country-region-data";
import type { Company } from "../../../../types/companies";
import type { ContractType } from "../../../../types/jobs";
import { Search } from "lucide-react";

export default function FiltersJobs({
  allCompanies,
  selectedCountry,
  regionsSelected,
  contractTypeSelected,
  selectedCompany,
  search,
  setCurrentPage,
  setSelectedCountry,
  setSelectedRegions,
  setSelectedContractType,
  setSelectedCompany,
  setSearch,
}: {
  allCompanies?: Company[];
  selectedCountry?: string;
  regionsSelected?: string[];
  contractTypeSelected?: ContractType;
  selectedCompany?: number;
  search?: string;
  setSelectedCountry: Dispatch<SetStateAction<string | undefined>>;
  setSelectedRegions: Dispatch<SetStateAction<string[] | undefined>>;
  setSelectedContractType: Dispatch<SetStateAction<ContractType | undefined>>;
  setSelectedCompany: Dispatch<SetStateAction<number | undefined>>;
  setCurrentPage: Dispatch<SetStateAction<number>>;
  setSearch: Dispatch<SetStateAction<string | undefined>>;
}) {
  const { t } = useTranslation();

  const countries = useMemo(() => {
    return allCountries.map(([name, code]) => {
      const adjustedName = name === "Israel" ? "Occupied Palestine" : name;
      return {
        name: adjustedName,
        code,
      };
    });
  }, []);

  const regions = useMemo(() => {
    return (
      allCountries.find(
        (c) =>
          c[0] === selectedCountry ||
          (selectedCountry === "Occupied Palestine" && c[0] === "Israel")
      )?.[2] || []
    );
  }, [selectedCountry]);

  // ---- Contract Type values ----
  const contractTypeValues = useMemo(() => {
    return {
      [t("contractTypes.fullTime")]: "full_time",
      [t("contractTypes.partTime")]: "part_time",
      [t("contractTypes.internship")]: "internship",
      [t("contractTypes.freelance")]: "freelance",
      [t("contractTypes.shortTerm")]: "short_term",
      [t("contractTypes.apprenticeship")]: "apprenticeship",
      [t("contractTypes.graduateProgram")]: "graduate_program",
      [t("contractTypes.remote")]: "remote",
    };
  }, [t]);

  // ---- Custom react-select controls ----
  const controlCountry = (
    props: ControlProps<{ value: string; label: string }, false>
  ) => (
    <components.Control {...props} className="pl-2">
      <Globe className="ml-2 mr-2 w-5 h-5 text-gray-500 shrink-0" />
      {props.children}
    </components.Control>
  );

  const controlRegions = (props: ControlProps<any, true>) => (
    <components.Control {...props} className="pl-2">
      <Map className="ml-2 mr-2 w-5 h-5 text-gray-500 shrink-0" />
      {props.children}
    </components.Control>
  );

  const controlContract = (
    props: ControlProps<{ value: string; label: string }, false>
  ) => (
    <components.Control {...props} className="pl-2">
      <Briefcase className="ml-2 mr-2 w-5 h-5 text-gray-500 shrink-0" />
      {props.children}
    </components.Control>
  );

  const CompanyControl = (
    props: ControlProps<
      {
        value: number | "all";
        label: string;
      },
      false
    >
  ) => (
    <components.Control {...props}>
      <div className="pl-2 flex items-center">
        <Building2 className="w-5 h-5 text-gray-500 mr-2" />
      </div>
      {props.children}
    </components.Control>
  );

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 px-6 mt-6">
      {/* Search */}

      <div className="relative w-full">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 w-5 h-5" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("search")}
          className="w-full border border-gray-300 rounded-xl pl-10 pr-4 py-2 text-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition"
        />
      </div>

      {/* Company Select */}
      <Select<
        {
          value: number | "all";
          label: string;
        },
        false
      >
        options={[
          { value: "all", label: t("allCompanies") },
          ...(allCompanies?.map((company) => ({
            value: company.id,
            label: company.name,
          })) ?? []),
        ]}
        value={
          selectedCompany
            ? {
                value: selectedCompany,
                label:
                  allCompanies?.find((c) => c.id === selectedCompany)?.name ??
                  t("selectCompany"),
              }
            : { value: "all", label: t("allCompanies") }
        }
        onChange={(
          option: SingleValue<{
            value: number | "all";
            label: string;
          }>
        ) => {
          const value =
            option?.value === "all" ? undefined : Number(option?.value);
          setSelectedCompany(value);
          setCurrentPage(1);
        }}
        isClearable
        isSearchable
        className="text-lg"
        components={{ Control: CompanyControl }}
        styles={{
          control: (base, state) => ({
            ...base,
            borderRadius: "0.75rem",
            borderColor: state.isFocused ? "#3b82f6" : "#d1d5db",
            boxShadow: state.isFocused ? "0 0 0 1px #3b82f6" : "none",
            "&:hover": { borderColor: "#9ca3af" },
            minHeight: "48px",
            paddingLeft: "4px",
          }),
        }}
      />

      {/* Country Select */}
      <Select<{ value: string; label: string }, false>
        options={countries.map(({ name }) => ({ value: name, label: name }))}
        value={
          selectedCountry
            ? { value: selectedCountry, label: selectedCountry }
            : null
        }
        onChange={(option) => {
          setSelectedCountry(option ? option.value : undefined);
          setSelectedRegions(undefined);
          setCurrentPage(1);
        }}
        placeholder={t("selectCountry")}
        components={{ Control: controlCountry }}
        className="text-lg"
        isClearable
        styles={{
          control: (base, state) => ({
            ...base,
            borderRadius: "0.75rem",
            borderColor: state.isFocused ? "#3b82f6" : "#d1d5db",
            boxShadow: state.isFocused ? "0 0 0 1px #3b82f6" : "none",
            "&:hover": { borderColor: "#9ca3af" },
            minHeight: "48px",
          }),
        }}
      />

      {/* Region Select */}
      <Select<{ value: string; label: string }, true>
        isMulti
        options={regions.map(([name]) => ({ value: name, label: name }))}
        value={regionsSelected?.map((r) => ({ value: r, label: r })) ?? []}
        onChange={(selected) => {
          setSelectedRegions(
            selected.length ? selected.map((opt) => opt.value) : undefined
          );
          setCurrentPage(1);
        }}
        placeholder={t("selectRegion")}
        components={{ Control: controlRegions }}
        className="text-lg"
        isClearable
        styles={{
          control: (base, state) => ({
            ...base,
            borderRadius: "0.75rem",
            borderColor: state.isFocused ? "#3b82f6" : "#d1d5db",
            boxShadow: state.isFocused ? "0 0 0 1px #3b82f6" : "none",
            "&:hover": { borderColor: "#9ca3af" },
            minHeight: "48px",
          }),
        }}
      />

      {/* Contract Type Select */}
      <Select<{ value: string; label: string }, false>
        options={Object.entries(contractTypeValues).map(([label, value]) => ({
          value,
          label,
        }))}
        value={
          contractTypeSelected
            ? {
                value: contractTypeSelected,
                label:
                  Object.keys(contractTypeValues).find(
                    (label) =>
                      contractTypeValues[label] === contractTypeSelected
                  ) ?? contractTypeSelected,
              }
            : null
        }
        onChange={(option) => {
          setSelectedContractType(
            option ? (option.value as ContractType) : undefined
          );
          setCurrentPage(1);
        }}
        placeholder={t("selectContractType")}
        components={{ Control: controlContract }}
        className="text-lg"
        isClearable
        styles={{
          control: (base, state) => ({
            ...base,
            borderRadius: "0.75rem",
            borderColor: state.isFocused ? "#3b82f6" : "#d1d5db",
            boxShadow: state.isFocused ? "0 0 0 1px #3b82f6" : "none",
            "&:hover": { borderColor: "#9ca3af" },
            minHeight: "48px",
          }),
        }}
      />
    </div>
  );
}
