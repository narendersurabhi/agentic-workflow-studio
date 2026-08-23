import type { RefObject } from "react";

import Button from "../../components/ui/Button";
import Input from "../../components/ui/Input";
import Textarea from "../../components/ui/Textarea";
import SkillCommandPalette from "../skills/SkillCommandPalette";
import type { CapabilityItem as SkillCapabilityItem, Skill } from "../skills/types";

export type ChatComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  sending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  showSkillPalette: boolean;
  onShowSkillPalette: (show: boolean) => void;
  skills: Skill[];
  capabilities: SkillCapabilityItem[];
  showSaveSkillForm: boolean;
  onToggleSaveSkillForm: () => void;
  saveSkillName: string;
  onSaveSkillNameChange: (value: string) => void;
  saveSkillDesc: string;
  onSaveSkillDescChange: (value: string) => void;
  saveSkillError: string | null;
  onSaveSkill: () => void;
  onCancelSaveSkill: () => void;
};

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  sending,
  textareaRef,
  showSkillPalette,
  onShowSkillPalette,
  skills,
  capabilities,
  showSaveSkillForm,
  onToggleSaveSkillForm,
  saveSkillName,
  onSaveSkillNameChange,
  saveSkillDesc,
  onSaveSkillDescChange,
  saveSkillError,
  onSaveSkill,
  onCancelSaveSkill,
}: ChatComposerProps) {
  return (
    <>
      <div className="relative">
        {showSkillPalette ? (
          <SkillCommandPalette
            skills={skills}
            capabilities={capabilities}
            onSelectSkill={(expanded) => {
              onChange(expanded);
              onShowSkillPalette(false);
              setTimeout(() => textareaRef.current?.focus(), 0);
            }}
            onSelectCapability={(id) => {
              onChange(value ? `${value} ${id}` : id);
              onShowSkillPalette(false);
              setTimeout(() => textareaRef.current?.focus(), 0);
            }}
            onClose={() => {
              onShowSkillPalette(false);
              setTimeout(() => textareaRef.current?.focus(), 0);
            }}
          />
        ) : null}
        <Textarea
          ref={textareaRef}
          rows={3}
          className="resize-none"
          value={value}
          onChange={(event) => {
            const nextValue = event.target.value;
            onChange(nextValue);
            if ((event.nativeEvent as InputEvent).data === "/") onShowSkillPalette(true);
            else if (showSkillPalette && nextValue === "") onShowSkillPalette(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              onSubmit();
            }
            if (event.key === "Escape") onShowSkillPalette(false);
          }}
          placeholder="Ask for work in natural language. Type / for Skills. Cmd/Ctrl+Enter sends."
        />
      </div>
      <div className="flex items-center justify-between gap-3">
        <Button variant="secondary" size="sm" onClick={onToggleSaveSkillForm}>
          Save as Skill
        </Button>
        <Button variant="primary" onClick={onSubmit} disabled={sending || !value.trim()}>
          {sending ? "Sending…" : "Send"}
        </Button>
      </div>
      {showSaveSkillForm ? (
        <div className="rounded-xl border border-subtle bg-surface-1 p-4 space-y-3">
          <div className="text-xs font-semibold text-text-md">Save as Skill</div>
          {saveSkillError ? <div className="text-xs text-rose-500">{saveSkillError}</div> : null}
          <Input
            placeholder="Skill name"
            value={saveSkillName}
            onChange={(e) => onSaveSkillNameChange(e.target.value)}
          />
          <Input
            placeholder="Description (optional)"
            value={saveSkillDesc}
            onChange={(e) => onSaveSkillDescChange(e.target.value)}
          />
          <div className="flex gap-2 justify-end">
            <Button variant="secondary" size="sm" onClick={onCancelSaveSkill}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={onSaveSkill}>
              Save
            </Button>
          </div>
        </div>
      ) : null}
    </>
  );
}

export default ChatComposer;
