import { ShoppingPlanResponse } from './api';

class PlanStore {
  private savedPlans: ShoppingPlanResponse[] = [];
  private readonly MAX_PLANS = 5;

  savePlan(plan: ShoppingPlanResponse): boolean {
    if (this.savedPlans.length >= this.MAX_PLANS) {
      return false;
    }
    this.savedPlans.push(plan);
    return true;
  }

  getSavedPlans(): ShoppingPlanResponse[] {
    return [...this.savedPlans];
  }

  getPlanByIndex(index: number): ShoppingPlanResponse | null {
    if (index >= 0 && index < this.savedPlans.length) {
      return this.savedPlans[index];
    }
    return null;
  }

  deletePlan(index: number): void {
    if (index >= 0 && index < this.savedPlans.length) {
      this.savedPlans.splice(index, 1);
    }
  }

  clearPlans(): void {
    this.savedPlans = [];
  }
}

export const planStore = new PlanStore();
