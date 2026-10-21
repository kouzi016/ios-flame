#pragma once
#include <stdint.h>

/*
 * flame's NT37280 panel runs in DSI command mode: it only shows what the
 * MDP pushes on a CTL start. CPU writes to the splash buffer appear only
 * while pingpong autorefresh refetches it on every TE.
 */
struct mdp_state {
	uint32_t pp0, pp1;	/* PP_AUTOREFRESH_CONFIG before we touched it */
	uint32_t ctl0_flush;	/* CTL0 FLUSH as ABL left it */
	int kicked;		/* 1: autorefresh was off and we enabled it */
};

void mdp_autorefresh(struct mdp_state *st);
