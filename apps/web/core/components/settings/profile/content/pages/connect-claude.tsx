/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Zil Ops: how to connect Claude to Ops over MCP (OAuth connector at /mcp, see docs/ops-mcp.md)
import { useTranslation } from "@plane/i18n";
import { CopyIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { copyTextToClipboard } from "@plane/utils";
// components
import { ProfileSettingsHeading } from "@/components/settings/profile/heading";

const CONNECTOR_NAME = "Zil Ops";
const CLI_NAME = "zil-ops";

function CopyField({ value, onCopy }: { value: string; onCopy: (value: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onCopy(value)}
      className="font-mono flex w-full items-center justify-between gap-3 rounded-md border-[0.5px] border-subtle bg-layer-1 px-3 py-2 text-left text-13 text-primary outline-none hover:bg-layer-1-hover"
    >
      <span className="truncate">{value}</span>
      <CopyIcon className="h-4 w-4 flex-shrink-0 text-placeholder" />
    </button>
  );
}

function Steps({ title, steps }: { title: string; steps: React.ReactNode[] }) {
  return (
    <section className="flex flex-col gap-3">
      <h6 className="text-body-sm-medium text-primary">{title}</h6>
      <ol className="flex list-decimal flex-col gap-2 pl-5 text-body-xs-regular text-secondary">
        {steps.map((step, index) => (
          // the steps are a fixed list, never reordered
          // oxlint-disable-next-line react/no-array-index-key
          <li key={index}>{step}</li>
        ))}
      </ol>
    </section>
  );
}

export function ConnectClaudeProfileSettings() {
  const { t } = useTranslation();
  const connectorUrl = `${window.location.origin}/mcp`;
  const cliCommand = `claude mcp add --transport http ${CLI_NAME} ${connectorUrl}`;

  const copy = (value: string) => {
    void copyTextToClipboard(value).then(() =>
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: `${t("success")}!`,
        message: t("account_settings.connect_claude.copied"),
      })
    );
  };

  return (
    // capped width: the settings column grows to fit its content, and these lines are long
    <div className="flex size-full max-w-160 flex-col gap-8">
      <ProfileSettingsHeading
        title={t("account_settings.connect_claude.title")}
        description={t("account_settings.connect_claude.description")}
      />
      <section className="flex flex-col gap-2">
        <span className="text-body-xs-medium text-tertiary">{t("account_settings.connect_claude.url_label")}</span>
        <CopyField value={connectorUrl} onCopy={copy} />
      </section>
      <Steps
        title={t("account_settings.connect_claude.app.title")}
        steps={[
          t("account_settings.connect_claude.app.step_1"),
          t("account_settings.connect_claude.app.step_2", { name: CONNECTOR_NAME }),
          t("account_settings.connect_claude.app.step_3"),
          t("account_settings.connect_claude.app.step_4"),
        ]}
      />
      <Steps
        title={t("account_settings.connect_claude.code.title")}
        steps={[
          <div key="command" className="flex flex-col gap-2">
            <span>{t("account_settings.connect_claude.code.step_1")}</span>
            <CopyField value={cliCommand} onCopy={copy} />
          </div>,
          t("account_settings.connect_claude.code.step_2", { name: CLI_NAME }),
        ]}
      />
      <p className="rounded-md border-[0.5px] border-subtle px-3 py-2 text-body-xs-regular text-tertiary">
        {t("account_settings.connect_claude.manage")}
      </p>
    </div>
  );
}
