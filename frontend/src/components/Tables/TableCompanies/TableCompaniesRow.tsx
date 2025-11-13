import { useState, useMemo, type Dispatch, type SetStateAction } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import type { CompanyInfo } from "../../../types/companies";
import useUpdateCompany from "../../../hooks/companies/useUpdateCompany";
import {
  getEditCompanySchema,
  type EditCompanyForm,
} from "./validationEditCompany";
import { zodResolver } from "@hookform/resolvers/zod";
import { useTranslation } from "react-i18next";

export default function TableCompaniesRow({
  company,
  isSelected,
  setSelected,
}: {
  company: CompanyInfo;
  isSelected: boolean;
  setSelected: Dispatch<SetStateAction<number[]>>;
}) {
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [visibleCount, setVisibleCount] = useState(5);
  const visibleEmails =
    company?.emails && company?.emails.slice(0, visibleCount);

  const statusColors: Record<string, string> = {
    idle: "bg-gray-300 text-gray-800",
    queued: "bg-yellow-400 text-[#194056]",
    in_progress: "bg-blue-400 text-white",
    done: "bg-green-500 text-white",
    error: "bg-red-500 text-white",
  };

  const {
    id,
    name,
    website,
    internalJobListingPages,
    externalJobListingPages,
    numberJobs,
    lastCheckedDate,
    status,
  } = company;

  const editCompanySchema = getEditCompanySchema(t);

  const {
    control,
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm({
    defaultValues: {
      id,
      name,
      website,
      internalJobListingPages:
        internalJobListingPages?.map((v) => ({ value: v })) ?? [],
      externalJobListingPages:
        externalJobListingPages?.map((v) => ({ value: v })) ?? [],
      emails: company.emails?.map((v) => ({ value: v })) ?? [],
    },
    resolver: zodResolver(editCompanySchema),
  });

  const {
    fields: internalFields,
    append: appendInternal,
    remove: removeInternal,
  } = useFieldArray({
    control,
    name: "internalJobListingPages",
  });

  const {
    fields: externalFields,
    append: appendExternal,
    remove: removeExternal,
  } = useFieldArray({
    control,
    name: "externalJobListingPages",
  });

  const {
    mutateCompany,
    isPendingMutateCompany,
    isSuccessMutateCompany,
    isErrorMutateCompany,
    message,
  } = useUpdateCompany();

  const onSubmit = (data: EditCompanyForm) => {
    const cleanedData = {
      ...data,
      internalJobListingPages:
        data.internalJobListingPages
          ?.map((item) => item.value)
          .filter((v): v is string => !!v?.trim()) ?? [],
      externalJobListingPages:
        data.externalJobListingPages
          ?.map((item) => item.value)
          .filter((v): v is string => !!v?.trim()) ?? [],
      emails:
        data.emails
          ?.map((item) => item.value)
          .filter((v): v is string => !!v?.trim()) ?? [],
    };

    mutateCompany(cleanedData);

    setIsEditing(false);
  };

  const handleSelect = (id: number, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...prev, id] : prev.filter((i) => i !== id)
    );
  };

  const hideCheckbox = useMemo(
    () => status === "queued" || status === "in_progress",
    [status]
  );

  const {
    fields: emailFields,
    append: appendEmail,
    remove: removeEmail,
  } = useFieldArray({
    control,
    name: "emails",
  });

  return (
    <tr
      className={`border-b transition ${
        isSelected ? "bg-yellow-100" : "hover:bg-yellow-50"
      }`}
    >
      {/* Checkbox */}
      <td className="px-4 py-3 text-center">
        {!hideCheckbox && (
          <input
            type="checkbox"
            checked={isSelected}
            onChange={(e) => handleSelect(id, e.target.checked)}
            className="w-4 h-4 accent-yellow-400 cursor-pointer"
          />
        )}
      </td>

      {/* Name */}
      <td className="px-4 py-3 font-medium text-blue-dark">
        {isEditing ? (
          <>
            <input
              {...register("name")}
              className="border border-gray-300 rounded-md px-2 py-1 w-full text-sm"
            />
            {errors.name && (
              <p className="text-xs text-red-500 mt-1">{errors.name.message}</p>
            )}
          </>
        ) : (
          name
        )}
      </td>

      {/* Website */}
      <td className="px-4 py-3">
        {isEditing ? (
          <>
            <input
              {...register("website")}
              className="border border-gray-300 rounded-md px-2 py-1 w-full text-sm"
            />
            {errors.website && (
              <p className="text-xs text-red-500 mt-1">
                {errors.website.message}
              </p>
            )}
          </>
        ) : (
          <a
            href={website}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 underline"
          >
            {website}
          </a>
        )}
      </td>

      {/* Internal job listing pages */}
      <td className="px-4 py-3 space-y-2">
        {isEditing ? (
          <div className="flex flex-col gap-2">
            {internalFields.map((field, idx) => (
              <div key={field.id} className="flex items-center gap-2">
                <input
                  {...register(`internalJobListingPages.${idx}.value` as const)}
                  className="border border-gray-300 rounded-md px-2 py-1 w-full text-sm"
                  placeholder={`${t("internalCareerPageLink")} #${idx + 1}`}
                />
                <button
                  type="button"
                  onClick={() => removeInternal(idx)}
                  className="bg-red-500 text-white rounded-md px-2 py-1 hover:bg-red-600"
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => appendInternal({ value: "" })}
              className="bg-yellow-400 text-blue-dark rounded-md px-3 py-1 hover:bg-yellow-300 w-fit text-sm"
            >
              + Add
            </button>
            {errors.internalJobListingPages && (
              <p className="text-xs text-red-500 mt-1">
                {errors.internalJobListingPages.message as string}
              </p>
            )}
          </div>
        ) : internalJobListingPages?.length ? (
          internalJobListingPages.map((page, idx) => (
            <a
              key={idx}
              href={page}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-sm text-blue-500 hover:underline"
            >
              {page}
            </a>
          ))
        ) : (
          <span className="text-gray-400 text-sm">—</span>
        )}
      </td>

      {/* External job listing pages */}
      <td className="px-4 py-3 space-y-2">
        {isEditing ? (
          <div className="flex flex-col gap-2">
            {externalFields.map((field, idx) => (
              <div key={field.id} className="flex items-center gap-2">
                <input
                  {...register(`externalJobListingPages.${idx}.value` as const)}
                  className="border border-gray-300 rounded-md px-2 py-1 w-full text-sm"
                  placeholder={`${t("externalCareerPageLink")} #${idx + 1}`}
                />
                <button
                  type="button"
                  onClick={() => removeExternal(idx)}
                  className="bg-red-500 text-white rounded-md px-2 py-1 hover:bg-red-600"
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => appendExternal({ value: "" })}
              className="bg-yellow-400 text-blue-dark rounded-md px-3 py-1 hover:bg-yellow-300 w-fit text-sm"
            >
              + {t("add")}
            </button>
            {errors.externalJobListingPages && (
              <p className="text-xs text-red-500 mt-1">
                {errors.externalJobListingPages.message as string}
              </p>
            )}
          </div>
        ) : externalJobListingPages?.length ? (
          externalJobListingPages.map((page, idx) => (
            <a
              key={idx}
              href={page}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-sm text-blue-500 hover:underline"
            >
              {page}
            </a>
          ))
        ) : (
          <span className="text-gray-400 text-sm">—</span>
        )}
      </td>

      {/* Emails */}
      <td className="px-4 py-3 space-y-2">
        {isEditing ? (
          <div className="flex flex-col gap-2">
            {emailFields.map((field, idx) => (
              <div key={field.id} className="flex items-center gap-2">
                <input
                  {...register(`emails.${idx}.value` as const)}
                  className="border border-gray-300 rounded-md px-2 py-1 w-full text-sm"
                  placeholder={`${t("email")} #${idx + 1}`}
                />
                <button
                  type="button"
                  onClick={() => removeEmail(idx)}
                  className="bg-red-500 text-white rounded-md px-2 py-1 hover:bg-red-600"
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => appendEmail({ value: "" })}
              className="bg-yellow-400 text-blue-dark rounded-md px-3 py-1 hover:bg-yellow-300 w-fit text-sm"
            >
              + {t("add")}
            </button>
            {errors.emails && (
              <p className="text-xs text-red-500 mt-1">
                {errors.emails.message as string}
              </p>
            )}
          </div>
        ) : company.emails && company.emails?.length ? (
          <div className="flex flex-col gap-1">
            {visibleEmails?.map((email, idx) => (
              <p key={idx} className="text-sm text-gray-700">
                {email}
              </p>
            ))}

            {company.emails.length > 5 && (
              <button
                type="button"
                onClick={() => {
                  if (visibleCount >= (company.emails?.length ?? 0)) {
                    setVisibleCount(5); // reset
                  } else {
                    setVisibleCount((prev) =>
                      Math.min(prev + 5, company.emails?.length ?? 0)
                    );
                  }
                }}
                className="cursor-pointer text-blue-600 text-sm font-medium hover:underline mt-1 self-start"
              >
                {visibleCount < company.emails.length
                  ? t("showMore", {
                      count: company.emails.length - visibleCount,
                    })
                  : t("showLess")}
              </button>
            )}
          </div>
        ) : (
          <span className="text-gray-400 text-sm">—</span>
        )}
      </td>

      {/* Number of jobs */}
      <td className="px-4 py-3 text-gray-700">{numberJobs}</td>

      {/* Last checked date */}
      <td className="px-4 py-3 text-gray-700">{lastCheckedDate ?? "N/A"}</td>

      {/* Status */}
      <td className="px-4 py-3">
        {status && (
          <span
            className={`inline-block px-3 py-1 rounded-full text-xs font-semibold ${statusColors[status]}`}
          >
            {t(status).toUpperCase()}
          </span>
        )}
      </td>

      {/* Actions */}
      <td className="px-4 py-3">
        <div className="flex flex-col">
          {isEditing ? (
            <div className="flex gap-2">
              <button
                onClick={handleSubmit(onSubmit)}
                disabled={isPendingMutateCompany}
                className="bg-green-600 text-white px-3 py-1 rounded-md hover:bg-green-700"
              >
                {isPendingMutateCompany ? t("saving") : t("save")}
              </button>
              <button
                onClick={() => {
                  setIsEditing(false);
                  reset();
                }}
                className="bg-gray-300 text-blue-dark px-3 py-1 rounded-md hover:bg-gray-400"
              >
                {t("cancel")}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setIsEditing(true)}
              className="bg-yellow-400 text-blue-dark px-3 py-1 rounded-md hover:bg-yellow-300"
            >
              {t("edit")}
            </button>
          )}

          {isSuccessMutateCompany && (
            <p className="text-green-600 text-sm font-semibold mt-1">
              {message}
            </p>
          )}
          {isErrorMutateCompany && (
            <p className="text-red-600 text-sm font-semibold mt-1">{message}</p>
          )}
        </div>
      </td>
    </tr>
  );
}
