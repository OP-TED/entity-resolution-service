Feature: Cross-instance ERE outcome notification

  Background:
    Given the Redis pub/sub infrastructure is available

  Scenario: ERE outcome processed by one instance unblocks waiter on another
    Given two AsyncResolutionWaiter instances sharing a Redis Pub/Sub channel
    And instance A is waiting on triad_key "SRCIDrequestidORGANISATION"
    When instance B publishes "SRCIDrequestidORGANISATION" to the notifications channel
    Then instance A's event is set within 1 second
    And instance B's waiter has no live event for "SRCIDrequestidORGANISATION"

  Scenario: Notification lost during subscriber reconnect degrades to timeout
    Given a NotificationSubscriberWorker is connected to Redis
    And a waiter is waiting on triad_key "xyz789" with a 0.1 second timeout
    When the Redis connection drops before the notification is published
    Then the waiter times out without receiving a signal
    And the worker reconnects and resumes processing subsequent messages

  Scenario: Notification lost but canonical decision in Mongo is still returned
    Given a coordinator whose subscriber missed the notification for triad_key "srcrec001Org"
    And the canonical decision for "srcrec001Org" is already persisted in MongoDB
    When the coordinator resolves the entity mention with a short time budget
    Then the coordinator returns the canonical decision via the Mongo-fallback safety net
    And no provisional identifier is issued
