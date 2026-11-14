# Temporary paywall pause

Production uses KRUVIM_PAYWALL_PAUSED=true. This disables paid access checks, checkout, portal and credit debits, and hides billing navigation and notices. Provider selection is unchanged. No payment code or customer records are deleted.

Restore by setting KRUVIM_PAYWALL_PAUSED=false and redeploying. Previous production: dpl_DQwxLTappR18nbuR4bTBHgeRTvxw, commit e0cffe3d97d424bf84217f25f2b132ed148cfaf9.

This switch does not cancel or pause existing recurring subscriptions at the payment provider.
