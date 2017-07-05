from card import CardGroup, Card


class Player:
    def __init__(self, name):
        self.cards = []
        self.candidates = []
        self.need_analyze = True
        self.name = name
        self.is_lord = False
        self.trainable = False

    def draw(self, group):
        self.need_analyze = True
        if type(group) is list:
            self.cards += group
        else:
            self.cards.append(group)

    def discard(self, group):
        self.need_analyze = True
        if type(group) is list:
            for c in group:
                self.cards.remove(c)
        else:
            self.cards.remove(group)

    def respond(self, last_player, cards, before_player, next_player):
        if self.need_analyze:
            self.candidates = CardGroup.analyze(self.cards)

        self.need_analyze = False
        if last_player is None or self is last_player:
            if CardGroup.folks(self.cards) == 2:
                self.discard(self.candidates[-1].cards)
                return self, self.candidates[-1], False
            elif not next_player.is_lord and len(next_player.cards) == 1:
                for group in self.candidates:
                    if group.type == 'single':
                        self.discard(group.cards)
                        return self, group, False
                self.discard(self.candidates[0].cards)
                return self, self.candidates[0], False
            elif next_player.is_lord and len(next_player.cards) == 1:
                for group in self.candidates:
                    if group.type != 'single':
                        self.discard(group.cards)
                        return self, group, False
                self.discard(self.candidates[-1].cards)
                return self, self.candidates[-1], False
            else:
                for group in self.candidates:
                    if group.type != 'single' or Card.to_value(group.cards[0]) < Card.to_value('A'):
                        self.discard(group.cards)
                        return self, group, False
                self.discard(self.candidates[0].cards)
                return self, self.candidates[0], False
            # print "player %s cards:" % self.name
            # print self.cards
            # print "player %s respond:" % self.name
            # print self.candidates[0].cards
            # self.discard(self.candidates[0].cards)
            # return self.name, self.candidates[0]
        elif not last_player.is_lord:
            if CardGroup.folks(self.cards) <= 2:
                for c in self.candidates:
                    if c.bigger_than(cards):
                        self.discard(c.cards)
                        return self, c, False
                return last_player, cards, True
            elif before_player.is_lord and last_player is not before_player:
                return last_player, cards, True
            else:
                for c in self.candidates:
                    if c.bigger_than(cards) and cards.type not in ['bomb', 'bigbang'] \
                            and Card.to_value(c.cards[0]) < Card.to_value('A'):
                        self.discard(c.cards)
                        return self, c, False
                return last_player, cards, True
        else:
            for c in self.candidates:
                if c.bigger_than(cards) and c.type not in ['bomb', 'bigbang']:
                    self.discard(c.cards)
                    return self, c, False
            # use bomb
            for c in self.candidates:
                if c.bigger_than(cards):
                    self.discard(c.cards)
                    return self, c, False
            return last_player, cards, True
