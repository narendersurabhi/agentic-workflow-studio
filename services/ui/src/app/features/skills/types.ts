export type SkillCondition = {
  operator: "exists" | "not_exists" | "contains";
  value?: string | null;
};

export type SkillStep = {
  id: string;
  order: number;
  type: "capability" | "goal_text";
  capability_id?: string | null;
  goal_template?: string | null;
  inputs: Record<string, string | number | boolean>;
  condition?: SkillCondition | null;
};

export type Skill = {
  id: string;
  name: string;
  description?: string | null;
  version: number;
  built_in: boolean;
  owner_id?: string | null;
  instructions?: string | null;
  steps: SkillStep[];
  created_at: string;
  updated_at: string;
};

export type SkillCreate = {
  name: string;
  description?: string | null;
  instructions?: string | null;
  steps: SkillStep[];
};

export type SkillUpdate = {
  name?: string;
  description?: string | null;
  instructions?: string | null;
  steps?: SkillStep[];
};

export type CapabilityItem = {
  id: string;
  description: string;
  group: string;
  subgroup: string;
  required_inputs: string[];
};
