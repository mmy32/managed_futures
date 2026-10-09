"""Past-only source selection, separate from the exact supplied-data reproduction."""
from pathlib import Path
import numpy as np
import pandas as pd
from src.data_processing.endpoints import endpoints
from src.config import FUTURES_UNDERLYING_DIR, PROJECT_ROOT, QPS_OUTPUT_DIR

ROOT = PROJECT_ROOT


def select_source(own_returns, fallback_returns, months, minimum_history=36, decision_lag=2):
    """Commit to ER only after a complete past window, then never backfill from RL.

    Rule is fixed before evaluating performance. It does not inspect RL's future
    end date or this month's realized return to decide which source to hold.
    """
    if minimum_history < 1 or decision_lag < 1:
        raise ValueError('Source selection requires positive history and lag')
    selected=pd.Series(index=months,dtype=float)
    source=pd.Series('RL',index=months,dtype=object)
    records=[];adopted=False
    for month in months:
        cutoff=month-decision_lag
        window=pd.period_range(cutoff-minimum_history+1,cutoff,freq='M')
        available=fallback_returns.reindex(window).notna().all()
        if available:adopted=True
        chosen='ER' if adopted else 'RL'
        source.loc[month]=chosen
        selected.loc[month]=(fallback_returns if adopted else own_returns).get(month,np.nan)
        records.append(dict(month=month,source=chosen,information_through=cutoff,
                            source_known_at=cutoff.end_time,complete_fallback_window=bool(available)))
    return selected,source,pd.DataFrame(records)


def load_strategy_inputs(settings,write=False):
    returns=pd.read_csv(QPS_OUTPUT_DIR / 'construction/monthly_returns_research.csv',index_col=0)
    returns.index=pd.PeriodIndex(returns.index,freq='M')
    independent={}
    for name in ['RL','ER']:
        raw=pd.read_csv(FUTURES_UNDERLYING_DIR / f'{name}.csv',index_col=0,parse_dates=True)
        closes=endpoints(raw,returns.index).endpoint_close
        independent[name]=closes/closes.shift(1)-1
    rule=settings.get('source_selection',{})
    selected,chosen,schedule=select_source(independent['RL'],independent['ER'],returns.index,
                                         rule.get('minimum_history',36),rule.get('decision_lag_months',2))
    returns['RL']=selected
    # A predeclared source label remains defined even if a realized return is missing.
    source=pd.DataFrame({a:a for a in returns.columns},index=returns.index)
    source['RL']=chosen
    known_at=pd.Series(pd.to_datetime(schedule.source_known_at).to_numpy(),index=returns.index,name='source_known_at')
    if write:
        out=QPS_OUTPUT_DIR / 'construction'
        returns.to_csv(out/'monthly_returns_strategy.csv',float_format='%.17g')
        source.to_csv(out/'strategy_source.csv')
        known_at.to_csv(out/'strategy_source_known_at.csv')
        schedule.to_csv(out/'strategy_source_schedule.csv',index=False)
    return returns,source,known_at,schedule
