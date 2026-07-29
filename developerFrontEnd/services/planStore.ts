import { ShoppingPlanResponse } from './api';

export interface SavedPlan {
  /** Stable identity. Never reused, never shifts when another plan is deleted. */
  id: string;
  savedAt: number;
  plan: ShoppingPlanResponse;
}

/**
 * In-memory store for saved plans.
 *
 * Plans used to be addressed by ARRAY INDEX (`/results?savedIndex=2`). Deleting
 * a plan spliced the array, so every link after it silently pointed at a
 * different plan than the one the user had opened. Entries now carry a stable
 * id and lookup is by id.
 *
 * NOTE: still memory-only — saved plans do not survive a reload. That is a
 * separate issue; this class only fixes the identity bug.
 */
class PlanStore {
  private savedPlans: SavedPlan[] = [];
  private readonly MAX_PLANS = 5;
  private seq = 0;

  private nextId(): string {
    this.seq += 1;
    return `plan-${Date.now().toString(36)}-${this.seq}`;
  }

  /** Returns the new plan's id, or null when the cap is reached. */
  savePlan(plan: ShoppingPlanResponse): string | null {
    if (this.savedPlans.length >= this.MAX_PLANS) {
      return null;
    }
    const entry: SavedPlan = { id: this.nextId(), savedAt: Date.now(), plan };
    this.savedPlans.push(entry);
    return entry.id;
  }

  getSavedPlans(): SavedPlan[] {
    return [...this.savedPlans];
  }

  getPlanById(id: string): ShoppingPlanResponse | null {
    return this.savedPlans.find((p) => p.id === id)?.plan ?? null;
  }

  deleteById(id: string): void {
    this.savedPlans = this.savedPlans.filter((p) => p.id !== id);
  }

  get isFull(): boolean {
    return this.savedPlans.length >= this.MAX_PLANS;
  }

  get max(): number {
    return this.MAX_PLANS;
  }

  clearPlans(): void {
    this.savedPlans = [];
  }
}

export const planStore = new PlanStore();
